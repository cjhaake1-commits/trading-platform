from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .brokers.alpaca_crypto_exit import AlpacaCryptoExitPaperBroker
from .brokers.practice_orders import (
    submit_alpaca_paper_crypto_market_order,
    submit_alpaca_paper_crypto_stop_limit,
    submit_alpaca_paper_protected_order,
    submit_oanda_practice_market_order,
)
from .brokers.safety import alpaca_open_positions, close_alpaca_position, close_oanda_position, oanda_open_positions
from .capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL, pillar_for_asset
from .crypto_exit import AlpacaCryptoExitCoordinator
from .execution_safety import IdempotencyStore
from .learning import load_learned_parameters
from .marketdata import YahooHistoricalData
from .models import AssetClass, Instrument, PortfolioState, Side, TradeIntent, TradeProposal
from .order_test_app import _sync_submitted_position
from .portfolio_ledger import PortfolioLedger
from .preflight import run_preflight
from .reconciliation import normalize_alpaca_positions, normalize_oanda_positions
from .risk import RiskContext, RiskEngine
from .runtime import JobResult
from .scanner import CandidateScanner
from .strategies import BaselineStrategies

DEFAULT_ALPACA_UNIVERSE = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "TSLA",
    "GOOGL",
    "AMD",
    "AVGO",
    "NFLX",
    "PLTR",
    "COIN",
    "MSTR",
    "SMCI",
    "JPM",
    "BAC",
    "GS",
    "XOM",
    "CVX",
    "LLY",
    "UNH",
    "COST",
)
DEFAULT_OANDA_UNIVERSE = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD", "EUR/JPY", "GBP/JPY")
DEFAULT_CRYPTO_UNIVERSE = ("BTC/USD", "ETH/USD")


@dataclass(frozen=True)
class AutonomousPaperConfig:
    ledger_path: str = "var/autotrader/portfolio.db"
    idempotency_path: str = "var/autotrader/idempotency.db"
    learned_parameters_path: str = "var/autotrader/learning/learned_parameters.json"
    initial_equity: float = TOTAL_PAPER_CAPITAL
    cadence_seconds: float = 60.0
    lookback_days: int = 7
    interval: str = "15m"
    minimum_candidate_score: float = 5.0
    momentum_only_score: float = 12.0
    take_profit_r_multiple: float = 1.5
    max_entries_per_cycle: int = 3
    alpaca_crypto_min_notional: float = 10.0
    alpaca_universe: tuple[str, ...] = DEFAULT_ALPACA_UNIVERSE
    oanda_universe: tuple[str, ...] = DEFAULT_OANDA_UNIVERSE
    crypto_universe: tuple[str, ...] = DEFAULT_CRYPTO_UNIVERSE


@dataclass(frozen=True)
class RankedSignal:
    instrument: Instrument
    score: float
    proposal: TradeProposal
    votes: tuple[str, ...]


def choose_long_signal(
    instrument: Instrument, bars, *, scanner=None, strategies=None, minimum_score=5.0, momentum_only_score=12.0
) -> RankedSignal | None:
    scanner = scanner or CandidateScanner()
    strategies = strategies or BaselineStrategies()
    candidate = scanner.score_instrument(instrument, bars)
    if candidate is None or candidate.score < minimum_score or candidate.momentum_pct <= 0:
        return None
    proposals = (
        strategies.sma_cross(instrument, bars),
        strategies.breakout(instrument, bars),
        strategies.mean_reversion(instrument, bars),
    )
    buys = [p for p in proposals if p is not None and p.side is Side.BUY]
    if not buys and candidate.score < momentum_only_score:
        return None
    entry = candidate.last_price
    stop = min(candidate.suggested_stop, entry * 0.995)
    if stop <= 0 or stop >= entry:
        return None
    votes = tuple(p.source for p in buys) or ("scanner_momentum",)
    confidence = min(0.95, 0.50 + 0.10 * len(votes) + candidate.score / 450.0)
    proposal = TradeProposal(
        instrument.symbol,
        instrument.asset_class,
        Side.BUY,
        entry,
        stop,
        confidence,
        f"autonomous:{'+'.join(votes)}",
        f"scanner_score={candidate.score:.2f}; momentum={candidate.momentum_pct:.2f}%; votes={','.join(votes)}",
        TradeIntent.ENTER,
    )
    return RankedSignal(instrument, candidate.score, proposal, votes)


class AutonomousPaperTradingJob:
    name = "autonomous-paper-trading"

    def __init__(self, config: AutonomousPaperConfig | None = None) -> None:
        self.config = config or AutonomousPaperConfig()
        self.cadence_seconds = self.config.cadence_seconds
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        self.risk = RiskEngine()
        self.idempotency = IdempotencyStore(self.config.idempotency_path)

    def run(self, now: datetime) -> JobResult:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        ledger = PortfolioLedger(self.config.ledger_path)
        self._sync_broker_flat_positions(ledger)
        preflight = run_preflight(
            ledger_path=self.config.ledger_path,
            idempotency_path=self.config.idempotency_path,
            initial_equity=self.config.initial_equity,
        )
        if not preflight.ready:
            return JobResult(
                True,
                "Autonomous paper cycle skipped by safety preflight",
                {"failed_checks": list(preflight.failed_checks), "messages": list(preflight.messages)},
            )

        learned = load_learned_parameters(self.config.learned_parameters_path)
        minimum_score = learned.get("minimum_candidate_score", self.config.minimum_candidate_score)
        momentum_score = learned.get("momentum_only_score", self.config.momentum_only_score)
        histories = self._load_histories(now)
        if not histories:
            return JobResult(
                True, "Autonomous paper cycle found no usable market data", {"learned_parameters": learned}
            )

        exits = self._manage_take_profits(preflight.portfolio, histories)
        if exits:
            return JobResult(
                True, "Autonomous paper cycle managed exits", {"exits": exits, "learned_parameters": learned}
            )

        loaded = ledger.load_portfolio()
        portfolio = (
            PortfolioState(self.config.initial_equity, self.config.initial_equity) if loaded is None else loaded[0]
        )
        diagnostics, signals = [], []
        for instrument, bars in histories.items():
            if instrument.symbol in portfolio.positions:
                continue
            candidate = self.scanner.score_instrument(instrument, bars)
            if candidate is not None:
                diagnostics.append(
                    {
                        "symbol": instrument.symbol,
                        "asset_class": instrument.asset_class.value,
                        "score": round(candidate.score, 2),
                        "momentum_pct": round(candidate.momentum_pct, 3),
                        "last_price": candidate.last_price,
                    }
                )
            signal = choose_long_signal(
                instrument,
                bars,
                scanner=self.scanner,
                strategies=self.strategies,
                minimum_score=minimum_score,
                momentum_only_score=momentum_score,
            )
            if signal is not None:
                signals.append(signal)

        diagnostics.sort(key=lambda x: float(x["score"]), reverse=True)
        forex = sorted(
            [s for s in signals if s.instrument.asset_class is AssetClass.FOREX], key=lambda x: x.score, reverse=True
        )
        crypto = sorted(
            [s for s in signals if s.instrument.asset_class is AssetClass.CRYPTO], key=lambda x: x.score, reverse=True
        )
        equities = sorted(
            [s for s in signals if s.instrument.asset_class not in {AssetClass.FOREX, AssetClass.CRYPTO}],
            key=lambda x: x.score,
            reverse=True,
        )
        signals = forex + crypto + equities
        counts = {
            "scanned": len(histories),
            "forex_scanned": sum(1 for i in histories if i.asset_class is AssetClass.FOREX),
            "crypto_scanned": sum(1 for i in histories if i.asset_class is AssetClass.CRYPTO),
            "forex_qualified": len(forex),
            "crypto_qualified": len(crypto),
            "equity_qualified": len(equities),
        }
        if not signals:
            return JobResult(
                True,
                "Autonomous paper cycle found no qualifying entry",
                {
                    **counts,
                    "qualified_signals": 0,
                    "top_candidates": diagnostics[:10],
                    "pillar_allocations": PILLAR_ALLOCATIONS,
                    "learned_parameters": learned,
                },
            )

        entries, rejections, failures, duplicates, sizing = [], [], [], [], []
        for signal in signals:
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
            pillar = pillar_for_asset(signal.instrument.asset_class)
            pillar_limit = PILLAR_ALLOCATIONS[pillar]
            pillar_notional = sum(
                abs(p.quantity * p.average_price)
                for p in portfolio.positions.values()
                if pillar_for_asset(p.asset_class) == pillar
            )
            if pillar_notional >= pillar_limit:
                rejections.append(
                    {
                        "symbol": signal.instrument.symbol,
                        "pillar": pillar,
                        "reason": f"pillar capital fully allocated ({pillar_notional:.2f} >= {pillar_limit:.2f})",
                    }
                )
                continue
            gross = sum(abs(p.quantity * p.average_price) for p in portfolio.positions.values())
            decision = self.risk.evaluate(
                signal.proposal,
                portfolio,
                RiskContext(peak_equity=fresh.peak_equity, gross_notional=gross, asset_class_notional=pillar_notional),
            )
            if not decision.approved:
                rejections.append({"symbol": signal.instrument.symbol, "pillar": pillar, "reason": decision.reason})
                continue
            remaining_notional = max(pillar_limit - pillar_notional, 0.0)
            capacity_quantity = remaining_notional / signal.proposal.entry_price
            if signal.instrument.asset_class is AssetClass.CRYPTO:
                pillar_risk_dollars = pillar_limit * 0.0125
                pillar_risk_quantity = pillar_risk_dollars / signal.proposal.risk_per_unit
                order_quantity = round(min(decision.quantity, capacity_quantity, pillar_risk_quantity), 8)
                calculated_notional = order_quantity * signal.proposal.entry_price
                if order_quantity <= 0 or calculated_notional < self.config.alpaca_crypto_min_notional:
                    sizing.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "pillar": pillar,
                            "reason": "order notional below broker minimum",
                            "calculated_notional": round(calculated_notional, 4),
                            "broker_minimum_notional": self.config.alpaca_crypto_min_notional,
                            "risk_quantity": decision.quantity,
                        }
                    )
                    continue
                broker = "alpaca-crypto-paper"
            else:
                order_quantity = float(math.floor(min(decision.quantity, capacity_quantity)))
                if order_quantity < 1:
                    sizing.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "pillar": pillar,
                            "risk_quantity": decision.quantity,
                            "capacity_quantity": capacity_quantity,
                            "reason": "pillar capacity rounds below one whole unit/share",
                        }
                    )
                    continue
                broker = "oanda-practice" if signal.instrument.asset_class is AssetClass.FOREX else "alpaca-paper"
            bucket = now.astimezone(UTC).strftime("%Y%m%dT%H%M")
            key = self.idempotency.make_key(
                broker=broker,
                symbol=signal.instrument.symbol,
                side="buy",
                intent="enter",
                quantity=order_quantity,
                strategy_id=signal.proposal.source,
                decision_bucket=bucket,
            )
            if not self.idempotency.reserve(
                key,
                broker=broker,
                symbol=signal.instrument.symbol,
                side="buy",
                intent="enter",
                ttl_seconds=max(int(self.cadence_seconds * 2), 600),
                now=now,
            ):
                duplicates.append({"symbol": signal.instrument.symbol, "broker": broker})
                continue
            client_id = f"auto-{bucket}-{signal.instrument.symbol.replace('/', '')}"[:48]
            try:
                protective_order_id = None
                if signal.instrument.asset_class is AssetClass.CRYPTO:
                    result = submit_alpaca_paper_crypto_market_order(
                        signal.instrument.symbol, side="buy", qty=order_quantity, client_order_id=client_id
                    )
                    broker_order_id = str(result.details.get("id") or "") or None
                    sync_broker = "alpaca"
                elif broker == "alpaca-paper":
                    result = submit_alpaca_paper_protected_order(
                        signal.instrument.symbol,
                        side="buy",
                        qty=order_quantity,
                        stop_price=signal.proposal.stop_price,
                        client_order_id=client_id,
                    )
                    broker_order_id = str(result.details.get("id") or "") or None
                    sync_broker = "alpaca"
                else:
                    result = submit_oanda_practice_market_order(
                        signal.instrument.symbol,
                        units=int(order_quantity),
                        stop_price=signal.proposal.stop_price,
                        client_order_id=client_id,
                    )
                    fill = result.details.get("order_fill_transaction")
                    broker_order_id = (
                        str(fill.get("orderID")) if isinstance(fill, dict) and fill.get("orderID") else None
                    )
                    sync_broker = "oanda"
                if not result.ok:
                    self.idempotency.release(key)
                    failures.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "broker": broker,
                            "quantity": order_quantity,
                            "message": result.message,
                            "details": result.details,
                        }
                    )
                    continue
                self.idempotency.mark_submitted(key, broker_order_id)
                sync = _sync_submitted_position(
                    broker=sync_broker,
                    symbol=signal.instrument.symbol,
                    stop_price=signal.proposal.stop_price,
                    ledger_path=self.config.ledger_path,
                    initial_equity=self.config.initial_equity,
                    expected_quantity=order_quantity,
                    asset_class=signal.instrument.asset_class,
                    attempts=24,
                    delay_seconds=0.25,
                )
                ledger.save_crypto_entry_state(
                    signal.instrument.symbol,
                    broker=broker,
                    lifecycle_state="reconciled",
                    requested_quantity=order_quantity,
                    submitted_quantity=order_quantity,
                    broker_filled_quantity=sync["quantity"],
                    broker_position_quantity=sync["quantity"],
                    reconciliation_difference=sync.get("reconciliation_difference"),
                    reconciliation_tolerance=0.005,
                    reconciliation_status=str(sync.get("reconciliation_status") or "broker_confirmed"),
                    protection_state="pending",
                    protection_quantity=None,
                    stop_price=signal.proposal.stop_price,
                    fill_price=sync["average_price"],
                    client_order_id=client_id,
                    protective_order_id=None,
                    entry_order_id=broker_order_id,
                    metadata={
                        "requested_quantity": order_quantity,
                        "submitted_quantity": order_quantity,
                        "broker_filled_quantity": sync["quantity"],
                        "broker_position_quantity": sync["quantity"],
                        "reconciliation_difference": sync.get("reconciliation_difference"),
                        "reconciliation_tolerance": 0.005,
                        "reconciliation_status": sync.get("reconciliation_status"),
                        "strategy_version": signal.proposal.source,
                        "model_version": "five_pillar_baseline_v1",
                        "proposal_stop": signal.proposal.stop_price,
                        "proposal_entry": signal.proposal.entry_price,
                    },
                )
                if signal.instrument.asset_class is AssetClass.CRYPTO:
                    protection = submit_alpaca_paper_crypto_stop_limit(
                        signal.instrument.symbol,
                        qty=abs(float(sync["quantity"])),
                        stop_price=signal.proposal.stop_price,
                        client_order_id=f"{client_id}-stop"[:48],
                    )
                    if not protection.ok:
                        ledger.save_crypto_entry_state(
                            signal.instrument.symbol,
                            broker=broker,
                            lifecycle_state="unprotected_position",
                            requested_quantity=order_quantity,
                            submitted_quantity=order_quantity,
                            broker_filled_quantity=sync["quantity"],
                            broker_position_quantity=sync["quantity"],
                            reconciliation_difference=sync.get("reconciliation_difference"),
                            reconciliation_tolerance=0.005,
                            reconciliation_status=str(sync.get("reconciliation_status") or "broker_confirmed"),
                            protection_state="failed",
                            protection_quantity=None,
                            stop_price=signal.proposal.stop_price,
                            fill_price=sync["average_price"],
                            client_order_id=client_id,
                            protective_order_id=None,
                            entry_order_id=broker_order_id,
                            metadata={
                                "protection_message": protection.message,
                                "protection_details": protection.details,
                            },
                        )
                        emergency = close_alpaca_position(signal.instrument.symbol, ledger_path=self.config.ledger_path)
                        failures.append(
                            {
                                "symbol": signal.instrument.symbol,
                                "broker": broker,
                                "quantity": order_quantity,
                                "message": "crypto entry filled but protective stop failed; emergency close requested",
                                "details": {
                                    "protection": protection.details,
                                    "protection_message": protection.message,
                                    "emergency_close_ok": emergency.ok,
                                    "emergency_close_message": emergency.message,
                                },
                            }
                        )
                        continue
                    protective_order_id = str(protection.details.get("id") or "") or None
                    ledger.save_crypto_entry_state(
                        signal.instrument.symbol,
                        broker=broker,
                        lifecycle_state="active",
                        requested_quantity=order_quantity,
                        submitted_quantity=order_quantity,
                        broker_filled_quantity=sync["quantity"],
                        broker_position_quantity=sync["quantity"],
                        reconciliation_difference=sync.get("reconciliation_difference"),
                        reconciliation_tolerance=0.005,
                        reconciliation_status=str(sync.get("reconciliation_status") or "broker_confirmed"),
                        protection_state="confirmed",
                        protection_quantity=abs(float(sync["quantity"])),
                        stop_price=signal.proposal.stop_price,
                        fill_price=sync["average_price"],
                        client_order_id=client_id,
                        protective_order_id=protective_order_id,
                        entry_order_id=broker_order_id,
                        metadata={
                            "protection_order": protection.details,
                            "strategy_version": signal.proposal.source,
                            "model_version": "five_pillar_baseline_v1",
                            "proposal_stop": signal.proposal.stop_price,
                            "proposal_entry": signal.proposal.entry_price,
                        },
                    )
                entries.append(
                    {
                        "broker": broker,
                        "pillar": pillar,
                        "symbol": signal.instrument.symbol,
                        "quantity": order_quantity,
                        "entry_reference": signal.proposal.entry_price,
                        "stop_price": signal.proposal.stop_price,
                        "score": signal.score,
                        "votes": list(signal.votes),
                        "risk_dollars": decision.max_loss_dollars,
                        "binding_constraint": decision.binding_constraint,
                        "broker_order_id": broker_order_id,
                        "protective_order_id": protective_order_id,
                        "ledger_sync": sync,
                    }
                )
            except Exception:
                self.idempotency.release(key)
                raise
        return JobResult(
            True,
            "Autonomous paper cycle completed",
            {
                "entries": entries,
                "qualified_signals": len(signals),
                **counts,
                "risk_rejections": rejections,
                "submission_failures": failures,
                "duplicate_skips": duplicates,
                "sizing_skips": sizing,
                "top_candidates": diagnostics[:10],
                "pillar_allocations": PILLAR_ALLOCATIONS,
                "learned_parameters": learned,
            },
        )

    def _load_histories(self, now: datetime):
        start = now - timedelta(days=max(self.config.lookback_days, 2))
        histories = {}
        etfs = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV"}
        instruments = [
            *(Instrument(s, AssetClass.ETF if s in etfs else AssetClass.STOCK) for s in self.config.alpaca_universe),
            *(Instrument(s, AssetClass.FOREX) for s in self.config.oanda_universe),
            *(Instrument(s, AssetClass.CRYPTO) for s in self.config.crypto_universe),
        ]
        for instrument in instruments:
            try:
                bars = self.feed.history(instrument, start, now, interval=self.config.interval)
            except Exception:
                continue
            if len(bars) >= 20:
                histories[instrument] = bars
        return histories

    def _manage_take_profits(self, portfolio: PortfolioState, histories) -> list[dict[str, object]]:
        exits = []
        by_symbol = {i.symbol: bars for i, bars in histories.items()}
        for symbol, position in list(portfolio.positions.items()):
            bars = by_symbol.get(symbol)
            if not bars:
                continue
            mark = bars[-1].close
            risk_per_unit = max(position.average_price - position.stop_price, 0.0)
            if risk_per_unit <= 0:
                continue
            target = position.average_price + self.config.take_profit_r_multiple * risk_per_unit
            if mark < target:
                continue
            if position.asset_class is AssetClass.CRYPTO:
                result = AlpacaCryptoExitCoordinator(
                    AlpacaCryptoExitPaperBroker.from_env(),
                    self.idempotency,
                    ledger_path=self.config.ledger_path,
                ).close(symbol, stop_price=position.stop_price)
            else:
                result = (
                    close_oanda_position(symbol, ledger_path=self.config.ledger_path)
                    if position.asset_class is AssetClass.FOREX
                    else close_alpaca_position(symbol, ledger_path=self.config.ledger_path)
                )
            exits.append(
                {
                    "symbol": symbol,
                    "mark": mark,
                    "target": target,
                    "ok": result.ok,
                    "message": result.message,
                }
            )
        return exits

    def _sync_broker_flat_positions(self, ledger: PortfolioLedger) -> None:
        loaded = ledger.load_portfolio()
        if loaded is None:
            return
        portfolio, peak = loaded
        try:
            alpaca = normalize_alpaca_positions(alpaca_open_positions().details.get("positions", []))
            oanda = normalize_oanda_positions(oanda_open_positions().details.get("positions", []))
        except Exception:
            return
        broker_symbols = {p.symbol for p in [*alpaca, *oanda] if abs(p.quantity) > 1e-12}
        changed = False
        for symbol in list(portfolio.positions):
            if symbol not in broker_symbols:
                del portfolio.positions[symbol]
                changed = True
        if changed:
            ledger.save_portfolio(portfolio, peak_equity=peak)
