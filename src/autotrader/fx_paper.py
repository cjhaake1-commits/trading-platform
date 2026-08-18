from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .brokers.practice_orders import submit_oanda_practice_market_order
from .capital_allocations import PILLAR_ALLOCATIONS, PILLAR_FOREX, TOTAL_PAPER_CAPITAL
from .execution_safety import IdempotencyStore
from .fx_signals import qualify_fx_signal
from .marketdata import YahooHistoricalData
from .models import AssetClass, Instrument, Side
from .order_test_app import _sync_submitted_position
from .preflight import run_preflight
from .risk import RiskContext, RiskEngine, RiskLimits
from .runtime import JobResult
from .scanner import CandidateScanner
from .strategies import BaselineStrategies

DEFAULT_OANDA_UNIVERSE = (
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
    "EUR/JPY",
    "GBP/JPY",
)


@dataclass(frozen=True)
class FxPaperConfig:
    ledger_path: str = "var/autotrader/portfolio.db"
    idempotency_path: str = "var/autotrader/idempotency.db"
    initial_equity: float = TOTAL_PAPER_CAPITAL
    cadence_seconds: float = 60.0
    lookback_days: int = 7
    interval: str = "15m"
    minimum_score: float = 1.5
    max_entries_per_cycle: int = 1
    min_entry_notional: float = 50.0
    universe: tuple[str, ...] = DEFAULT_OANDA_UNIVERSE


class FxPaperTradingJob:
    name = "oanda-fx-paper-trading"

    def __init__(self, config: FxPaperConfig | None = None) -> None:
        self.config = config or FxPaperConfig()
        self.cadence_seconds = self.config.cadence_seconds
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        # Short selling is enabled only inside this dedicated OANDA job. All hard
        # loss/drawdown/notional limits remain identical to the default profile.
        self.risk = RiskEngine(replace(RiskLimits(), allow_short_selling=True))
        self.idempotency = IdempotencyStore(self.config.idempotency_path)

    def run(self, now: datetime) -> JobResult:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        preflight = run_preflight(
            ledger_path=self.config.ledger_path,
            idempotency_path=self.config.idempotency_path,
            initial_equity=self.config.initial_equity,
        )
        if not preflight.ready:
            return JobResult(
                True,
                "OANDA FX cycle skipped by safety preflight",
                {"failed_checks": list(preflight.failed_checks), "messages": list(preflight.messages)},
            )

        histories = self._load_histories(now)
        diagnostics: list[dict[str, object]] = []
        qualified = []
        for instrument, bars in histories.items():
            if instrument.symbol in preflight.portfolio.positions:
                diagnostics.append({"symbol": instrument.symbol, "qualified": False, "reason": "position already open"})
                continue
            decision = qualify_fx_signal(
                instrument,
                bars,
                hour_utc=now.astimezone(UTC).hour,
                scanner=self.scanner,
                strategies=self.strategies,
                minimum_score=self.config.minimum_score,
            )
            diagnostics.append(decision.diagnostic)
            if decision.qualified and decision.proposal is not None:
                qualified.append(decision)

        qualified.sort(key=lambda item: item.score, reverse=True)
        counts = {"forex_scanned": len(histories), "forex_qualified": len(qualified), "fx_diagnostics": diagnostics}
        if not qualified:
            return JobResult(True, "OANDA FX cycle found no qualifying entry", counts)

        entries: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []
        sizing_skips: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        pillar_limit = PILLAR_ALLOCATIONS[PILLAR_FOREX]

        for signal in qualified:
            if len(entries) >= self.config.max_entries_per_cycle:
                break
            fresh = run_preflight(
                ledger_path=self.config.ledger_path,
                idempotency_path=self.config.idempotency_path,
                initial_equity=self.config.initial_equity,
            )
            if not fresh.ready:
                break

            portfolio = fresh.portfolio
            pillar_notional = sum(
                abs(position.quantity * position.average_price)
                for position in portfolio.positions.values()
                if position.asset_class is AssetClass.FOREX
            )
            if pillar_notional >= pillar_limit:
                rejections.append({"symbol": signal.proposal.symbol, "pillar": PILLAR_FOREX, "reason": f"pillar capital fully allocated ({pillar_notional:.2f} >= {pillar_limit:.2f})"})
                continue

            gross = sum(abs(position.quantity * position.average_price) for position in portfolio.positions.values())
            risk_decision = self.risk.evaluate(
                signal.proposal,
                portfolio,
                RiskContext(peak_equity=fresh.peak_equity, gross_notional=gross, asset_class_notional=pillar_notional),
            )
            if not risk_decision.approved:
                rejections.append({"symbol": signal.proposal.symbol, "pillar": PILLAR_FOREX, "side": signal.proposal.side.value, "reason": risk_decision.reason})
                continue

            remaining_notional = max(pillar_limit - pillar_notional, 0.0)
            if remaining_notional < self.config.min_entry_notional:
                sizing_skips.append({
                    "symbol": signal.proposal.symbol,
                    "pillar": PILLAR_FOREX,
                    "side": signal.proposal.side.value,
                    "remaining_notional": round(remaining_notional, 4),
                    "minimum_entry_notional": self.config.min_entry_notional,
                    "reason": "remaining FX pillar capacity below minimum meaningful entry notional",
                })
                continue

            capacity_quantity = remaining_notional / signal.proposal.entry_price
            order_quantity = int(math.floor(min(risk_decision.quantity, capacity_quantity)))
            proposed_notional = order_quantity * signal.proposal.entry_price
            if order_quantity < 1 or proposed_notional < self.config.min_entry_notional:
                sizing_skips.append({
                    "symbol": signal.proposal.symbol,
                    "pillar": PILLAR_FOREX,
                    "side": signal.proposal.side.value,
                    "risk_quantity": risk_decision.quantity,
                    "capacity_quantity": capacity_quantity,
                    "proposed_notional": round(proposed_notional, 4),
                    "minimum_entry_notional": self.config.min_entry_notional,
                    "reason": "FX order below minimum meaningful entry notional",
                })
                continue

            signed_units = order_quantity if signal.proposal.side is Side.BUY else -order_quantity
            bucket = now.astimezone(UTC).strftime("%Y%m%dT%H%M")
            key = self.idempotency.make_key(
                broker="oanda-practice",
                symbol=signal.proposal.symbol,
                side=signal.proposal.side.value,
                intent="enter",
                quantity=order_quantity,
                strategy_id=signal.proposal.source,
                decision_bucket=bucket,
            )
            if not self.idempotency.reserve(
                key,
                broker="oanda-practice",
                symbol=signal.proposal.symbol,
                side=signal.proposal.side.value,
                intent="enter",
                ttl_seconds=max(int(self.cadence_seconds * 2), 600),
                now=now,
            ):
                duplicates.append({"symbol": signal.proposal.symbol, "broker": "oanda-practice", "side": signal.proposal.side.value})
                continue

            client_id = f"fx-{bucket}-{signal.proposal.side.value[0]}-{signal.proposal.symbol.replace('/', '')}"[:48]
            try:
                result = submit_oanda_practice_market_order(
                    signal.proposal.symbol,
                    units=signed_units,
                    stop_price=signal.proposal.stop_price,
                    client_order_id=client_id,
                )
                if not result.ok:
                    self.idempotency.release(key)
                    failures.append({"symbol": signal.proposal.symbol, "broker": "oanda-practice", "side": signal.proposal.side.value, "units": signed_units, "message": result.message, "details": result.details})
                    continue

                fill = result.details.get("order_fill_transaction")
                broker_order_id = str(fill.get("orderID")) if isinstance(fill, dict) and fill.get("orderID") else None
                self.idempotency.mark_submitted(key, broker_order_id)
                sync = _sync_submitted_position(
                    broker="oanda",
                    symbol=signal.proposal.symbol,
                    stop_price=signal.proposal.stop_price,
                    ledger_path=self.config.ledger_path,
                    initial_equity=self.config.initial_equity,
                    expected_quantity=order_quantity,
                    asset_class=AssetClass.FOREX,
                    attempts=24,
                    delay_seconds=0.25,
                )
                entries.append({
                    "broker": "oanda-practice",
                    "pillar": PILLAR_FOREX,
                    "symbol": signal.proposal.symbol,
                    "side": signal.proposal.side.value,
                    "units": signed_units,
                    "entry_reference": signal.proposal.entry_price,
                    "stop_price": signal.proposal.stop_price,
                    "score": signal.score,
                    "votes": list(signal.votes),
                    "risk_dollars": risk_decision.max_loss_dollars,
                    "binding_constraint": risk_decision.binding_constraint,
                    "broker_order_id": broker_order_id,
                    "ledger_sync": sync,
                })
            except Exception:
                self.idempotency.release(key)
                raise

        return JobResult(True, "OANDA FX cycle completed", {**counts, "entries": entries, "risk_rejections": rejections, "sizing_skips": sizing_skips, "submission_failures": failures, "duplicate_skips": duplicates})

    def _load_histories(self, now: datetime):
        start = now - timedelta(days=max(self.config.lookback_days, 2))
        histories = {}
        for symbol in self.config.universe:
            instrument = Instrument(symbol, AssetClass.FOREX)
            try:
                bars = self.feed.history(instrument, start, now, interval=self.config.interval)
            except Exception:
                continue
            if len(bars) >= 20:
                histories[instrument] = bars
        return histories
