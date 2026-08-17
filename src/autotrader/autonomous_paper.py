from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .brokers.practice_orders import (
    submit_alpaca_paper_protected_order,
    submit_oanda_practice_market_order,
)
from .brokers.safety import (
    alpaca_open_positions,
    close_alpaca_position,
    close_oanda_position,
    oanda_open_positions,
)
from .execution_safety import IdempotencyStore
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
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL",
    "AMD", "AVGO", "NFLX", "PLTR", "COIN", "MSTR", "SMCI",
    "JPM", "BAC", "GS", "XOM", "CVX", "LLY", "UNH", "COST",
)
DEFAULT_OANDA_UNIVERSE = (
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD",
    "EUR/JPY", "GBP/JPY",
)


@dataclass(frozen=True)
class AutonomousPaperConfig:
    ledger_path: str = "var/autotrader/portfolio.db"
    idempotency_path: str = "var/autotrader/idempotency.db"
    initial_equity: float = 2000.0
    cadence_seconds: float = 60.0
    lookback_days: int = 7
    interval: str = "15m"
    minimum_candidate_score: float = 5.0
    momentum_only_score: float = 12.0
    take_profit_r_multiple: float = 1.5
    max_entries_per_cycle: int = 3
    min_forex_entries_when_qualified: int = 1
    alpaca_universe: tuple[str, ...] = DEFAULT_ALPACA_UNIVERSE
    oanda_universe: tuple[str, ...] = DEFAULT_OANDA_UNIVERSE


@dataclass(frozen=True)
class RankedSignal:
    instrument: Instrument
    score: float
    proposal: TradeProposal
    votes: tuple[str, ...]


def choose_long_signal(
    instrument: Instrument,
    bars,
    *,
    scanner: CandidateScanner | None = None,
    strategies: BaselineStrategies | None = None,
    minimum_score: float = 5.0,
    momentum_only_score: float = 12.0,
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
    buys = [proposal for proposal in proposals if proposal is not None and proposal.side is Side.BUY]
    if not buys and candidate.score < momentum_only_score:
        return None

    entry = candidate.last_price
    stop = min(candidate.suggested_stop, entry * 0.995)
    if stop <= 0 or stop >= entry:
        return None

    votes = tuple(proposal.source for proposal in buys) or ("scanner_momentum",)
    source = "+".join(votes)
    confidence = min(0.95, 0.50 + 0.10 * len(votes) + candidate.score / 450.0)
    proposal = TradeProposal(
        symbol=instrument.symbol,
        asset_class=instrument.asset_class,
        side=Side.BUY,
        entry_price=entry,
        stop_price=stop,
        confidence=confidence,
        source=f"autonomous:{source}",
        rationale=(
            f"scanner_score={candidate.score:.2f}; momentum={candidate.momentum_pct:.2f}%; "
            f"votes={','.join(votes)}"
        ),
        intent=TradeIntent.ENTER,
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
            return JobResult(True, "Autonomous paper cycle skipped by safety preflight", {
                "failed_checks": list(preflight.failed_checks), "messages": list(preflight.messages)
            })

        histories = self._load_histories(now)
        if not histories:
            return JobResult(True, "Autonomous paper cycle found no usable market data", {})

        exits = self._manage_take_profits(preflight.portfolio, histories)
        if exits:
            return JobResult(True, "Autonomous paper cycle managed exits", {"exits": exits})

        loaded = ledger.load_portfolio()
        portfolio = PortfolioState(self.config.initial_equity, self.config.initial_equity) if loaded is None else loaded[0]

        diagnostics: list[dict[str, object]] = []
        signals: list[RankedSignal] = []
        for instrument, bars in histories.items():
            if instrument.symbol in portfolio.positions:
                continue
            candidate = self.scanner.score_instrument(instrument, bars)
            if candidate is not None:
                diagnostics.append({
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class.value,
                    "score": round(candidate.score, 2),
                    "momentum_pct": round(candidate.momentum_pct, 3),
                    "last_price": candidate.last_price,
                })
            signal = choose_long_signal(
                instrument,
                bars,
                scanner=self.scanner,
                strategies=self.strategies,
                minimum_score=self.config.minimum_candidate_score,
                momentum_only_score=self.config.momentum_only_score,
            )
            if signal is not None:
                signals.append(signal)

        diagnostics.sort(key=lambda item: float(item["score"]), reverse=True)
        forex_signals = sorted(
            [s for s in signals if s.instrument.asset_class is AssetClass.FOREX],
            key=lambda item: item.score,
            reverse=True,
        )
        equity_signals = sorted(
            [s for s in signals if s.instrument.asset_class is not AssetClass.FOREX],
            key=lambda item: item.score,
            reverse=True,
        )
        # FX gets first opportunity each cycle when it has a valid signal. Global
        # risk limits still apply; this only prevents equities from always consuming
        # the queue first.
        signals = forex_signals + equity_signals

        if not signals:
            return JobResult(True, "Autonomous paper cycle found no qualifying entry", {
                "scanned": len(histories),
                "minimum_candidate_score": self.config.minimum_candidate_score,
                "momentum_only_score": self.config.momentum_only_score,
                "forex_scanned": sum(1 for i in histories if i.asset_class is AssetClass.FOREX),
                "forex_qualified": 0,
                "top_candidates": diagnostics[:10],
            })

        entries: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []
        submission_failures: list[dict[str, object]] = []
        duplicate_skips: list[dict[str, object]] = []
        sizing_skips: list[dict[str, object]] = []

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
            gross = sum(abs(p.quantity * p.average_price) for p in portfolio.positions.values())
            asset_notional = sum(
                abs(p.quantity * p.average_price)
                for p in portfolio.positions.values()
                if p.asset_class is signal.instrument.asset_class
            )
            decision = self.risk.evaluate(
                signal.proposal,
                portfolio,
                RiskContext(
                    peak_equity=fresh.peak_equity,
                    gross_notional=gross,
                    asset_class_notional=asset_notional,
                ),
            )
            if not decision.approved:
                rejections.append({
                    "symbol": signal.instrument.symbol,
                    "broker": "oanda-practice" if signal.instrument.asset_class is AssetClass.FOREX else "alpaca-paper",
                    "reason": decision.reason,
                })
                continue

            broker = "oanda-practice" if signal.instrument.asset_class is AssetClass.FOREX else "alpaca-paper"
            order_quantity = float(math.floor(decision.quantity))
            if order_quantity < 1:
                sizing_skips.append({
                    "symbol": signal.instrument.symbol,
                    "broker": broker,
                    "risk_quantity": decision.quantity,
                    "reason": "protected order quantity rounds below one whole unit/share",
                })
                continue

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
                duplicate_skips.append({"symbol": signal.instrument.symbol, "broker": broker})
                continue

            client_id = f"auto-{bucket}-{signal.instrument.symbol.replace('/', '')}"[:48]
            try:
                if broker == "alpaca-paper":
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
                    broker_order_id = str(fill.get("orderID")) if isinstance(fill, dict) and fill.get("orderID") else None
                    sync_broker = "oanda"

                if not result.ok:
                    self.idempotency.release(key)
                    submission_failures.append({
                        "symbol": signal.instrument.symbol,
                        "broker": broker,
                        "quantity": order_quantity,
                        "message": result.message,
                        "details": result.details,
                    })
                    continue

                self.idempotency.mark_submitted(key, broker_order_id)
                sync = _sync_submitted_position(
                    broker=sync_broker,
                    symbol=signal.instrument.symbol,
                    stop_price=signal.proposal.stop_price,
                    ledger_path=self.config.ledger_path,
                    initial_equity=self.config.initial_equity,
                    expected_quantity=order_quantity,
                    attempts=20,
                    delay_seconds=0.25,
                )
                entries.append({
                    "broker": broker,
                    "symbol": signal.instrument.symbol,
                    "quantity": order_quantity,
                    "entry_reference": signal.proposal.entry_price,
                    "stop_price": signal.proposal.stop_price,
                    "score": signal.score,
                    "votes": list(signal.votes),
                    "risk_dollars": decision.max_loss_dollars,
                    "binding_constraint": decision.binding_constraint,
                    "broker_order_id": broker_order_id,
                    "ledger_sync": sync,
                })
            except Exception:
                self.idempotency.release(key)
                raise

        return JobResult(True, "Autonomous paper cycle completed", {
            "entries": entries,
            "qualified_signals": len(signals),
            "forex_scanned": sum(1 for i in histories if i.asset_class is AssetClass.FOREX),
            "forex_qualified": len(forex_signals),
            "equity_qualified": len(equity_signals),
            "risk_rejections": rejections,
            "submission_failures": submission_failures,
            "duplicate_skips": duplicate_skips,
            "sizing_skips": sizing_skips,
            "top_candidates": diagnostics[:10],
            "scanned": len(histories),
        })

    def _load_histories(self, now: datetime):
        start = now - timedelta(days=max(self.config.lookback_days, 2))
        histories = {}
        etfs = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV"}
        instruments = [
            *(Instrument(symbol, AssetClass.ETF if symbol in etfs else AssetClass.STOCK) for symbol in self.config.alpaca_universe),
            *(Instrument(symbol, AssetClass.FOREX) for symbol in self.config.oanda_universe),
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
        exits: list[dict[str, object]] = []
        by_symbol = {instrument.symbol: bars for instrument, bars in histories.items()}
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
            if position.asset_class is AssetClass.FOREX or "/" in symbol:
                result = close_oanda_position(symbol, ledger_path=self.config.ledger_path)
            else:
                result = close_alpaca_position(symbol, ledger_path=self.config.ledger_path)
            exits.append({"symbol": symbol, "mark": mark, "target": target, "ok": result.ok, "message": result.message})
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
