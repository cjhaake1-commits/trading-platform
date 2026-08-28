from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .brokers.alpaca_crypto_exit import AlpacaCryptoExitPaperBroker
from .brokers.practice_orders import (
    alpaca_crypto_universe,
    alpaca_paper_order_status,
    crypto_quantity_for_notional,
    submit_alpaca_paper_crypto_market_order,
    submit_alpaca_paper_crypto_stop_limit,
    submit_alpaca_paper_protected_order,
    submit_oanda_practice_market_order,
)
from .brokers.safety import (
    alpaca_open_positions,
    cancel_alpaca_open_orders_for_symbol,
    close_alpaca_position,
    close_oanda_position,
    oanda_open_positions,
)
from .alpaca_backlog import reconcile_alpaca_equity_backlog
from .capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL, pillar_for_asset
from .crypto_exit import AlpacaCryptoExitCoordinator
from .execution_safety import IdempotencyStore
from .experiment_state import load_experiment_baseline_start, position_is_experiment_eligible
from .learning import load_learned_parameters
from .marketdata import YahooHistoricalData
from .models import AssetClass, Instrument, PortfolioState, Side, TradeIntent, TradeProposal
from .order_test_app import _sync_submitted_position
from .paper_experiment import (
    EdgeEstimate,
    PaperExperimentConfig,
        PaperExperimentLedger,
    estimate_edge,
    experimental_candidate,
        experimental_position_quantity_cap,
)
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
# Provider-confirmed Alpaca PAPER USD pairs.  This is intentionally a
# conservative liquid subset rather than the full asset catalog; provider
# minimums and the existing risk/capacity gates still decide eligibility.
DEFAULT_CRYPTO_UNIVERSE = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "LINK/USD",
    "AVAX/USD",
    "DOGE/USD",
    "LTC/USD",
    "BCH/USD",
)


def pillar_allocation_room(*, allocation: float, current_exposure: float, pending_capital: float) -> float:
    """Return spendable room after both filled and reserved exposure."""
    return max(float(allocation) - float(current_exposure) - float(pending_capital), 0.0)

EXECUTION_QUALITY_PATH = Path("var/autotrader/learning/crypto-execution-quality.json")


def _record_crypto_execution_quality(
    symbol: str,
    outcome: str,
    *,
    age_seconds: float | None = None,
    order_id: str | None = None,
    order_type: str | None = None,
    time_in_force: str | None = None,
    qty: float | None = None,
    notional: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    signal_score: float | None = None,
    expected_edge: float | None = None,
    filled_qty: float | None = None,
    average_fill: float | None = None,
    slippage: float | None = None,
) -> None:
    try:
        payload = json.loads(EXECUTION_QUALITY_PATH.read_text()) if EXECUTION_QUALITY_PATH.exists() else {}
        row = payload.setdefault(symbol, {"submitted": 0, "accepted": 0, "filled": 0, "partial": 0, "stale": 0, "canceled": 0, "rejected": 0, "events": [], "latencies": []})
        row[outcome] = int(row.get(outcome, 0)) + 1
        if age_seconds is not None:
            row.setdefault("latencies", []).append(round(age_seconds, 3))
            row["latencies"] = row["latencies"][-50:]
        submitted = max(int(row.get("submitted", 0)), 1)
        stale = int(row.get("stale", 0))
        filled = int(row.get("filled", 0))
        row["execution_quality_score"] = round(max(0.0, min(1.0, (filled + 0.5) / (submitted + 1) - 0.15 * stale / submitted)), 4)
        event = {"event": outcome, "timestamp": datetime.now(UTC).isoformat(), "order_id": order_id,
                 "order_type": order_type, "time_in_force": time_in_force, "qty": qty,
                 "notional": notional, "bid": bid, "ask": ask, "spread": (ask - bid) if bid is not None and ask is not None else None,
                 "signal_score": signal_score, "expected_edge": expected_edge, "age_seconds": age_seconds,
                 "filled_qty": filled_qty, "average_fill": average_fill, "slippage": slippage}
        row.setdefault("events", []).append(event)
        row["events"] = row["events"][-200:]
        if outcome in {"stale", "canceled", "rejected", "provider_error"}:
            prior = int(row.get("cooldown_events", 0)) + 1
            row["cooldown_events"] = prior
            row["cooldown_until"] = (datetime.now(UTC) + timedelta(seconds=min(900, 180 * prior))).isoformat()
        elif outcome in {"filled", "partial"}:
            row["cooldown_events"] = 0
            row.pop("cooldown_until", None)
        EXECUTION_QUALITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXECUTION_QUALITY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return


def _crypto_execution_penalty(symbol: str) -> float:
    try:
        row = json.loads(EXECUTION_QUALITY_PATH.read_text()).get(symbol, {})
        stale = float(row.get("stale", 0))
        submitted = max(float(row.get("submitted", 0)), 1.0)
        return min(10.0, stale / submitted * 10.0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def _crypto_execution_cooldown_active(symbol: str, now: datetime) -> bool:
    try:
        row = json.loads(EXECUTION_QUALITY_PATH.read_text()).get(symbol, {})
        until = row.get("cooldown_until")
        if not until:
            return False
        return datetime.fromisoformat(str(until).replace("Z", "+00:00")) > now
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


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
    max_unresolved_v2_per_pillar: int = 3
    alpaca_crypto_min_notional: float = 10.0
    alpaca_universe: tuple[str, ...] = DEFAULT_ALPACA_UNIVERSE
    oanda_universe: tuple[str, ...] = DEFAULT_OANDA_UNIVERSE
    crypto_universe: tuple[str, ...] = DEFAULT_CRYPTO_UNIVERSE
    crypto_exit_confirmation_cycles: int = 2
    crypto_stale_order_seconds: int = 900
    crypto_market_order_seconds: int = 90


@dataclass(frozen=True)
class RankedSignal:
    instrument: Instrument
    score: float
    proposal: TradeProposal
    votes: tuple[str, ...]
    mode: str = "BASELINE"
    edge: EdgeEstimate | None = None


def _broker_environment(broker: str) -> str:
    broker = broker.lower()
    if broker == "alpaca-paper":
        return "paper"
    if broker == "oanda-practice":
        return "practice"
    if broker == "alpaca-crypto-paper":
        return "paper"
    return "sim"


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
    return RankedSignal(
        instrument,
        candidate.score,
        proposal,
        votes,
        "BASELINE",
        estimate_edge(candidate, proposal, asset_class=instrument.asset_class, experimental=False),
    )


def choose_experimental_long_signal(
    instrument: Instrument,
    bars,
    *,
    scanner=None,
    strategies=None,
    config: PaperExperimentConfig | None = None,
) -> RankedSignal | None:
    config = config or PaperExperimentConfig.from_env()
    if not config.enabled:
        return None
    scanner = scanner or CandidateScanner()
    strategies = strategies or BaselineStrategies()
    candidate = scanner.score_instrument(instrument, bars)
    if candidate is None:
        return None
    proposals = (
        strategies.sma_cross(instrument, bars),
        strategies.breakout(instrument, bars),
        strategies.mean_reversion(instrument, bars),
    )
    selected = experimental_candidate(candidate, proposals, config=config)
    if selected is None:
        return None
    proposal, edge = selected
    return RankedSignal(instrument, candidate.score, proposal, (proposal.source,), "EXPERIMENTAL_PAPER", edge)


class AutonomousPaperTradingJob:
    name = "autonomous-paper-trading"

    def __init__(self, config: AutonomousPaperConfig | None = None) -> None:
        self.config = config or AutonomousPaperConfig()
        self.cadence_seconds = self.config.cadence_seconds
        self.experiment_baseline_start = load_experiment_baseline_start()
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        self.experiment = PaperExperimentConfig.from_env()
        self.experiment_ledger = PaperExperimentLedger()
        self.risk = RiskEngine()
        self.idempotency = IdempotencyStore(self.config.idempotency_path)
        self.unresolved_states = set(PortfolioLedger.unresolved_entry_states())
        self._crypto_exit_confirmations: dict[str, int] = {}
        self.crypto_data_diagnostics: dict[str, object] = {}

    def _active_v2_unresolved_by_pillar(self, ledger: PortfolioLedger) -> dict[str, int]:
        counts: dict[str, int] = {}
        for manifest in ledger.unresolved_entry_manifests():
            if str(manifest.get("created_at") or "") < self.experiment_baseline_start.isoformat():
                continue
            pillar = str(manifest.get("pillar") or "unknown")
            if pillar == "alpaca_crypto" and not self._crypto_manifest_is_live(manifest):
                continue
            counts[pillar] = counts.get(pillar, 0) + 1
        return counts

    def _active_v2_pending_by_pillar(self, ledger: PortfolioLedger) -> dict[str, float]:
        pending: dict[str, float] = {}
        for manifest in ledger.unresolved_entry_manifests():
            if str(manifest.get("created_at") or "") < self.experiment_baseline_start.isoformat():
                continue
            if str(manifest.get("lifecycle_state")) not in self.unresolved_states:
                continue
            if str(manifest.get("pillar") or "unknown") == "alpaca_crypto" and not self._crypto_manifest_is_live(manifest):
                continue
            approved = float(manifest.get("approved_notional") or 0.0)
            filled = float(manifest.get("filled_quantity") or 0.0)
            average = float(manifest.get("average_fill_price") or 0.0)
            remaining = max(approved - abs(filled * average), 0.0)
            pillar = str(manifest.get("pillar") or "unknown")
            pending[pillar] = pending.get(pillar, 0.0) + remaining
        return pending

    def _crypto_manifest_is_live(self, manifest: dict[str, object]) -> bool:
        """Count a Crypto manifest only while broker state still exists."""
        symbol = str(manifest.get("canonical_symbol") or "")
        if not symbol:
            return False
        try:
            broker = AlpacaCryptoExitPaperBroker.from_env()
            if broker.position(symbol) is not None:
                return True
            return bool(broker.open_orders(symbol))
        except Exception:
            # Unknown provider state fails closed for allocation purposes.
            return True

    def run(self, now: datetime) -> JobResult:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        ledger = PortfolioLedger(self.config.ledger_path)
        # Crypto manifests must be reconciled against the same authoritative
        # Alpaca PAPER endpoints immediately before candidate gating. The
        # equity-only active-v2 job is intentionally not sufficient here.
        try:
            crypto_reconciliation = reconcile_alpaca_equity_backlog(
                self.config.ledger_path, apply_paper_cleanup=True,
                scope="crypto", broker="alpaca-crypto-paper", budget_limit=12,
            )
            crypto_reconciliation_telemetry = {
                "crypto_manifest_reconciliation_state": "RECONCILING" if crypto_reconciliation.unresolved_after else "CLEAR",
                "crypto_manifest_unresolved_before": crypto_reconciliation.unresolved_before,
                "crypto_manifest_unresolved_after": crypto_reconciliation.unresolved_after,
            }
        except Exception as exc:
            # Provider uncertainty remains fail-closed; never resolve locally.
            crypto_reconciliation_telemetry = {
                "crypto_manifest_reconciliation_state": "DEGRADED",
                "crypto_manifest_reconciliation_error": type(exc).__name__,
            }
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
                True, "Autonomous paper cycle data unavailable", {
                    "learned_parameters": learned,
                    "crypto_data_diagnostics": self.crypto_data_diagnostics,
                    "data_failure": True,
                }
            )

        stale_orders = self._cancel_stale_crypto_orders(ledger, now)

        position_management, rotation_exits = self._manage_crypto_positions(preflight.portfolio, histories, ledger)
        exits = self._manage_take_profits(preflight.portfolio, histories)
        if rotation_exits or exits:
            return JobResult(
                True,
                "Autonomous paper cycle managed exits",
                {"exits": [*rotation_exits, *exits], "stale_orders": stale_orders, "position_management": position_management, "learned_parameters": learned},
            )

        loaded = ledger.load_portfolio()
        portfolio = (
            PortfolioState(self.config.initial_equity, self.config.initial_equity) if loaded is None else loaded[0]
        )
        strategy_portfolio = self._strategy_portfolio(portfolio, ledger)
        diagnostics, signals = [], []
        for instrument, bars in histories.items():
            if instrument.symbol in portfolio.positions:
                continue
            if instrument.asset_class is AssetClass.CRYPTO and _crypto_execution_cooldown_active(instrument.symbol, now):
                diagnostics.append({"symbol": instrument.symbol, "score": 0.0, "rejection": "EXECUTION_COOLDOWN"})
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
            champion_signal = choose_long_signal(
                instrument,
                bars,
                scanner=self.scanner,
                strategies=self.strategies,
                minimum_score=minimum_score,
                momentum_only_score=momentum_score,
            )
            challenger_signal = None
            if instrument.asset_class is AssetClass.CRYPTO:
                challenger_signal = choose_experimental_long_signal(
                    instrument,
                    bars,
                    scanner=self.scanner,
                    strategies=self.strategies,
                    config=self.experiment,
                )
                if candidate is not None:
                    reference = champion_signal or challenger_signal
                    entry = reference.proposal.entry_price if reference else candidate.last_price
                    stop = reference.proposal.stop_price if reference else candidate.suggested_stop
                    target = entry + 2.0 * abs(entry - stop) if stop and stop < entry else None
                    self.experiment_ledger.record_counterfactual(
                        symbol=instrument.symbol, occurred_at=bars[-1].timestamp,
                        champion_decision="ACCEPT" if champion_signal else "REJECT",
                        challenger_decision="ACCEPT" if challenger_signal else "REJECT",
                        entry_price=entry, quantity=1000.0 / entry if entry > 0 else 0.0,
                        stop_price=stop, target_price=target,
                        candidate_identity=f"{bars[-1].timestamp.isoformat()}|{candidate.score:.6f}",
                        features={
                            "score": candidate.score, "momentum_pct": candidate.momentum_pct,
                            "volatility": candidate.average_range_pct / 100.0,
                            "estimated_cost_rate": 0.004,
                            "champion_edge": champion_signal.edge.as_dict() if champion_signal else None,
                            "challenger_edge": challenger_signal.edge.as_dict() if challenger_signal else None,
                            "tag": "COUNTERFACTUAL_ONLY",
                        },
                    )
            signal = champion_signal
            if signal is None:
                signal = challenger_signal
            if signal is not None:
                self.experiment_ledger.record_decision(
                    pillar="alpaca_crypto" if instrument.asset_class is AssetClass.CRYPTO else "alpaca_equities",
                    symbol=instrument.symbol,
                    strategy=signal.proposal.source,
                    timeframe=self.config.interval,
                    lane=signal.mode,
                    decision="candidate",
                    entry_price=signal.proposal.entry_price,
                    edge=signal.edge,
                    features={"score": signal.score, "votes": signal.votes},
                )
                signals.append(signal)

        diagnostics.sort(key=lambda x: float(x["score"]), reverse=True)
        forex = sorted(
            [s for s in signals if s.instrument.asset_class is AssetClass.FOREX], key=lambda x: x.score, reverse=True
        )
        crypto = sorted(
            [s for s in signals if s.instrument.asset_class is AssetClass.CRYPTO],
            key=lambda x: x.score - _crypto_execution_penalty(x.instrument.symbol),
            reverse=True,
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
            "baseline_candidates": sum(1 for s in signals if s.mode == "BASELINE"),
            "experimental_candidates": sum(1 for s in signals if s.mode == "EXPERIMENTAL_PAPER"),
            "paper_experiment_enabled": self.experiment.enabled,
            "provider_crypto_universe": list(getattr(self, "provider_crypto_universe", ())),
            "eligible_crypto_universe": [i.symbol for i in histories if i.asset_class is AssetClass.CRYPTO],
            "experimental_position_cap_pct": self.experiment.experimental_position_cap_pct,
        }
        if not signals:
            return JobResult(
                True,
                "Autonomous paper cycle found no qualifying entry",
                {
                    **crypto_reconciliation_telemetry,
                    **counts,
                        "qualified_signals": 0,
                        "paper_experiment_enabled": self.experiment.enabled,
                    "top_candidates": diagnostics[:10],
                    "pillar_allocations": PILLAR_ALLOCATIONS,
                        "learned_parameters": learned,
                    "position_management": position_management,
                    "stale_orders": stale_orders,
                },
            )

        entries, rejections, failures, duplicates, sizing = [], [], [], [], []
        unresolved_by_pillar = self._active_v2_unresolved_by_pillar(ledger)
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
            strategy_portfolio = self._strategy_portfolio(portfolio, ledger)
            pillar = pillar_for_asset(signal.instrument.asset_class)
            if signal.mode == "EXPERIMENTAL_PAPER":
                if signal.edge is None or signal.edge.expected_net_edge <= signal.edge.required_edge:
                    rejections.append({"symbol": signal.instrument.symbol, "pillar": pillar, "mode": signal.mode, "reason": "experimental edge is not cost-positive"})
                    continue
            if unresolved_by_pillar.get(pillar, 0) >= self.config.max_unresolved_v2_per_pillar:
                rejections.append(
                    {
                        "symbol": signal.instrument.symbol,
                        "pillar": pillar,
                        "reason": "active-v2 reconciliation capacity exhausted",
                        "capacity_state": "RECONCILING",
                        "unresolved_active_v2": unresolved_by_pillar.get(pillar, 0),
                        "capacity": self.config.max_unresolved_v2_per_pillar,
                    }
                )
                continue
            pillar_limit = PILLAR_ALLOCATIONS[pillar]
            pillar_notional = sum(
                abs(p.quantity * p.average_price)
                for p in strategy_portfolio.positions.values()
                if pillar_for_asset(p.asset_class) == pillar
            )
            if signal.mode == "EXPERIMENTAL_PAPER" and pillar_notional >= pillar_limit * self.experiment.experimental_max_pillar_utilization:
                rejections.append({"symbol": signal.instrument.symbol, "pillar": pillar, "mode": signal.mode, "reason": "CAPITAL_CONCENTRATION_HOLD" if pillar == "alpaca_crypto" else "experimental capital envelope reached"})
                continue
            if pillar_notional >= pillar_limit:
                rejections.append(
                    {
                        "symbol": signal.instrument.symbol,
                        "pillar": pillar,
                        "reason": f"pillar capital fully allocated ({pillar_notional:.2f} >= {pillar_limit:.2f})",
                    }
                )
                continue
            existing_manifest = ledger.latest_unresolved_entry_manifest_for_symbol(
                signal.instrument.symbol.replace("_", "/").upper(), broker=(
                    "alpaca-crypto-paper"
                    if signal.instrument.asset_class is AssetClass.CRYPTO
                    else ("oanda-practice" if signal.instrument.asset_class is AssetClass.FOREX else "alpaca-paper")
                )
            )
            if existing_manifest is not None:
                duplicates.append(
                    {
                        "symbol": signal.instrument.symbol,
                        "broker": existing_manifest.get("broker"),
                        "manifest_id": existing_manifest.get("manifest_id"),
                        "lifecycle_state": existing_manifest.get("lifecycle_state"),
                        "reason": "existing unresolved manifest blocks duplicate entry",
                    }
                )
                continue
            gross = sum(abs(p.quantity * p.average_price) for p in strategy_portfolio.positions.values())
            decision = self.risk.evaluate(
                signal.proposal,
                strategy_portfolio,
                RiskContext(peak_equity=fresh.peak_equity, gross_notional=gross, asset_class_notional=pillar_notional),
            )
            if not decision.approved:
                rejections.append({"symbol": signal.instrument.symbol, "pillar": pillar, "reason": decision.reason})
                continue
            pending_by_pillar = self._active_v2_pending_by_pillar(ledger)
            committed_total = gross + sum(pending_by_pillar.values())
            pillar_committed = pillar_notional + pending_by_pillar.get(pillar, 0.0)
            requested_notional = decision.quantity * signal.proposal.entry_price
            available_total = max(TOTAL_PAPER_CAPITAL - committed_total, 0.0)
            available_pillar = max(pillar_limit - pillar_committed, 0.0)
            # A signal's unconstrained risk quantity can exceed the pillar
            # allocation.  Capacity is applied during deterministic sizing
            # below; reject only when no capital is actually available.
            if min(available_total, available_pillar) <= 0:
                rejections.append(
                    {
                        "symbol": signal.instrument.symbol,
                        "pillar": pillar,
                        "reason": "v2 capital reservation unavailable",
                        "capacity_state": "CAPITAL_RESERVED",
                        "requested_notional": requested_notional,
                        "available_total": available_total,
                        "available_pillar": available_pillar,
                    }
                )
                continue
            # Reservations are part of exposure governance.  Using only
            # current filled exposure here allowed multiple same-cycle
            # approvals to each spend the same remaining pillar capacity.
            remaining_notional = pillar_allocation_room(
                allocation=pillar_limit,
                current_exposure=pillar_notional,
                pending_capital=pending_by_pillar.get(pillar, 0.0),
            )
            capacity_quantity = remaining_notional / signal.proposal.entry_price
            if signal.instrument.asset_class is AssetClass.CRYPTO:
                pillar_risk_dollars = pillar_limit * 0.0125
                pillar_risk_quantity = pillar_risk_dollars / signal.proposal.risk_per_unit
                if signal.mode == "EXPERIMENTAL_PAPER":
                    pillar_risk_dollars *= self.experiment.experimental_risk_scale
                    pillar_risk_quantity = pillar_risk_dollars / signal.proposal.risk_per_unit
                requested_quantity = min(decision.quantity, capacity_quantity, pillar_risk_quantity)
                if signal.mode == "EXPERIMENTAL_PAPER":
                    requested_quantity *= self.experiment.experimental_risk_scale
                    requested_quantity = min(requested_quantity, experimental_position_quantity_cap(pillar_capital=pillar_limit, entry_price=signal.proposal.entry_price, config=self.experiment))
                provider_quantity, provider_reason = crypto_quantity_for_notional(
                    signal.instrument.symbol,
                    signal.proposal.entry_price,
                    max(requested_quantity * signal.proposal.entry_price, self.config.alpaca_crypto_min_notional),
                )
                if provider_reason:
                    sizing.append({"symbol": signal.instrument.symbol, "pillar": pillar, "reason": provider_reason})
                    continue
                order_quantity = round(float(provider_quantity), 9)
                calculated_notional = order_quantity * signal.proposal.entry_price
                if order_quantity <= 0 or calculated_notional + 1e-6 < self.config.alpaca_crypto_min_notional:
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
                if order_quantity > requested_quantity or calculated_notional > min(available_total, available_pillar):
                    sizing.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "pillar": pillar,
                            "reason": "PROVIDER_MINIMUM_EXCEEDS_RISK_CAP",
                            "provider_quantity": order_quantity,
                            "risk_quantity": requested_quantity,
                            "calculated_notional": calculated_notional,
                        }
                    )
                    continue
                broker = "alpaca-crypto-paper"
            else:
                requested_quantity = decision.quantity * (self.experiment.experimental_risk_scale if signal.mode == "EXPERIMENTAL_PAPER" else 1.0)
                order_quantity = float(math.floor(min(requested_quantity, capacity_quantity)))
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
                canonical_symbol = signal.instrument.symbol.replace("_", "/").upper()
                existing_manifest = ledger.latest_unresolved_entry_manifest_for_symbol(
                    canonical_symbol, broker=broker
                )
                if existing_manifest is not None:
                    duplicates.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "broker": broker,
                            "manifest_id": existing_manifest.get("manifest_id"),
                            "lifecycle_state": existing_manifest.get("lifecycle_state"),
                            "reason": "existing unresolved manifest blocks duplicate entry",
                            "resume_state": "existing_entry_reconciliation_resumed",
                        }
                    )
                    self.idempotency.release(key)
                    continue
                manifest_payload = {
                    "broker": broker,
                    "environment": _broker_environment(broker),
                    "pillar": pillar,
                    "canonical_symbol": canonical_symbol,
                    "broker_symbol": signal.instrument.symbol,
                    "side": signal.proposal.side.value,
                    "model_version": "five_pillar_baseline_v1" if signal.mode == "BASELINE" else "paper_experiment_challenger_v1",
                    "strategy_version": signal.proposal.source,
                    "confidence": signal.proposal.confidence,
                    "regime": signal.proposal.rationale or None,
                    "approved_entry": signal.proposal.entry_price,
                    "requested_quantity": order_quantity,
                    "approved_notional": order_quantity * signal.proposal.entry_price,
                    "approved_stop": signal.proposal.stop_price,
                    "approved_target": None,
                    "approved_dollar_risk": decision.max_loss_dollars,
                    "allocation_at_approval": pillar_notional,
                    "portfolio_risk_at_approval": gross,
                    "risk_engine_decision": decision.reason,
                    "lifecycle_state": "approved_manifest",
                    "client_order_id_namespace": client_id,
                    "lane": signal.mode,
                    "edge": signal.edge.as_dict() if signal.edge else None,
                    "order_type": "market",
                    "time_in_force": "ioc",
                }
                manifest_payload["fingerprint"] = PortfolioLedger.manifest_fingerprint(manifest_payload)
                manifest_id = manifest_payload["fingerprint"][:32]
                ledger.save_entry_manifest(
                    manifest_id=manifest_id,
                    created_at=now,
                    broker=broker,
                    environment=manifest_payload["environment"],
                    pillar=pillar,
                    canonical_symbol=manifest_payload["canonical_symbol"],
                    broker_symbol=manifest_payload["broker_symbol"],
                    side=signal.proposal.side.value,
                    model_version=manifest_payload["model_version"],
                    strategy_version=signal.proposal.source,
                    confidence=signal.proposal.confidence,
                    regime=manifest_payload["regime"],
                    approved_entry=signal.proposal.entry_price,
                    requested_quantity=order_quantity,
                    approved_notional=order_quantity * signal.proposal.entry_price,
                    approved_stop=signal.proposal.stop_price,
                    approved_target=None,
                    approved_dollar_risk=decision.max_loss_dollars,
                    allocation_at_approval=pillar_notional,
                    portfolio_risk_at_approval=gross,
                    risk_engine_decision=decision.reason,
                    lifecycle_state="approved_manifest",
                    client_order_id_namespace=client_id,
                    fingerprint=manifest_payload["fingerprint"],
                    metadata={"signal": signal.votes, "manifest": manifest_payload, "lane": signal.mode, "edge": signal.edge.as_dict() if signal.edge else None},
                )
                protective_order_id = None
                if signal.instrument.asset_class is AssetClass.CRYPTO:
                    result = submit_alpaca_paper_crypto_market_order(
                        signal.instrument.symbol, side="buy", qty=order_quantity, client_order_id=client_id,
                        time_in_force="ioc",
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
                    if signal.instrument.asset_class is AssetClass.CRYPTO:
                        _record_crypto_execution_quality(signal.instrument.symbol, "rejected", order_type="market", time_in_force="ioc", qty=order_quantity, notional=order_quantity * signal.proposal.entry_price, signal_score=signal.score, expected_edge=signal.edge.expected_net_edge if signal.edge else None)
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
                if signal.instrument.asset_class is AssetClass.CRYPTO:
                    _record_crypto_execution_quality(signal.instrument.symbol, "submitted", order_id=broker_order_id, order_type="market", time_in_force="ioc", qty=order_quantity, notional=order_quantity * signal.proposal.entry_price, signal_score=signal.score, expected_edge=signal.edge.expected_net_edge if signal.edge else None)
                    _record_crypto_execution_quality(signal.instrument.symbol, "accepted", order_id=broker_order_id, order_type="market", time_in_force="ioc", qty=order_quantity, notional=order_quantity * signal.proposal.entry_price, signal_score=signal.score, expected_edge=signal.edge.expected_net_edge if signal.edge else None)
                ledger.save_entry_manifest(
                    manifest_id=manifest_id,
                    created_at=now,
                    broker=broker,
                    environment=manifest_payload["environment"],
                    pillar=pillar,
                    canonical_symbol=manifest_payload["canonical_symbol"],
                    broker_symbol=manifest_payload["broker_symbol"],
                    side=signal.proposal.side.value,
                    model_version=manifest_payload["model_version"],
                    strategy_version=signal.proposal.source,
                    confidence=signal.proposal.confidence,
                    regime=manifest_payload["regime"],
                    approved_entry=signal.proposal.entry_price,
                    requested_quantity=order_quantity,
                    approved_notional=order_quantity * signal.proposal.entry_price,
                    approved_stop=signal.proposal.stop_price,
                    approved_target=None,
                    approved_dollar_risk=decision.max_loss_dollars,
                    allocation_at_approval=pillar_notional,
                    portfolio_risk_at_approval=gross,
                    risk_engine_decision=decision.reason,
                    lifecycle_state="order_submitted",
                    client_order_id_namespace=client_id,
                    fingerprint=manifest_payload["fingerprint"],
                    broker_order_id=broker_order_id,
                    submitted_quantity=order_quantity,
                    metadata={"submission": result.details, "lane": signal.mode, "edge": signal.edge.as_dict() if signal.edge else None, "order_type": manifest_payload.get("order_type"), "time_in_force": manifest_payload.get("time_in_force")},
                )
                try:
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
                        broker_order_id=broker_order_id,
                    )
                except RuntimeError:
                    if signal.instrument.asset_class is not AssetClass.CRYPTO:
                        raise
                    sync = {"reconciliation_status": "provider_terminal_pending", "quantity": None}
                reconciliation_status = str(sync.get("reconciliation_status") or "broker_confirmed")
                if signal.instrument.asset_class is AssetClass.CRYPTO and sync.get("quantity") is not None:
                    filled_qty = float(sync.get("quantity") or 0.0)
                    _record_crypto_execution_quality(
                        signal.instrument.symbol,
                        "filled" if filled_qty >= order_quantity else "partial",
                        order_id=broker_order_id,
                        order_type="market",
                        time_in_force="ioc",
                        qty=order_quantity,
                        notional=order_quantity * signal.proposal.entry_price,
                        signal_score=signal.score,
                        expected_edge=signal.edge.expected_net_edge if signal.edge else None,
                        filled_qty=filled_qty,
                        average_fill=float(sync.get("entry_price") or signal.proposal.entry_price),
                    )
                if signal.instrument.asset_class is AssetClass.CRYPTO and not sync.get("quantity") and broker_order_id:
                    terminal = alpaca_paper_order_status(broker_order_id)
                    status = str(terminal.details.get("status") or "").lower()
                    if terminal.ok and status in {"canceled", "expired", "rejected"}:
                        _record_crypto_execution_quality(
                            signal.instrument.symbol,
                            "canceled" if status == "canceled" else status,
                            order_id=broker_order_id,
                            order_type="market",
                            time_in_force="ioc",
                            qty=order_quantity,
                            notional=order_quantity * signal.proposal.entry_price,
                            signal_score=signal.score,
                            expected_edge=signal.edge.expected_net_edge if signal.edge else None,
                        )
                        ledger.mark_manifest_terminal(
                            manifest_id,
                            lifecycle_state=f"{status}_unfilled",
                            metadata={"provider_terminal_status": status, "provider_order": terminal.details},
                        )
                if sync.get("quantity") is not None:
                    ledger.save_crypto_entry_state(
                        signal.instrument.symbol,
                        broker=broker,
                        lifecycle_state=(
                            "reconciled"
                            if reconciliation_status in {"exact_match", "fractional_reconciliation", "broker_confirmed"}
                            else reconciliation_status
                        ),
                        requested_quantity=order_quantity,
                        submitted_quantity=order_quantity,
                        broker_filled_quantity=sync["quantity"],
                        broker_position_quantity=sync["quantity"],
                        reconciliation_difference=sync.get("reconciliation_difference"),
                        reconciliation_tolerance=0.005,
                        reconciliation_status=reconciliation_status,
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
                            "model_version": manifest_payload["model_version"],
                            "proposal_stop": signal.proposal.stop_price,
                            "proposal_entry": signal.proposal.entry_price,
                            "order_status": sync.get("order_status"),
                        },
                    )
                else:
                    ledger.save_crypto_entry_state(
                        signal.instrument.symbol,
                        broker=broker,
                        lifecycle_state=reconciliation_status,
                        requested_quantity=order_quantity,
                        submitted_quantity=order_quantity,
                        broker_filled_quantity=None,
                        broker_position_quantity=None,
                        reconciliation_difference=sync.get("reconciliation_difference"),
                        reconciliation_tolerance=0.005,
                        reconciliation_status=reconciliation_status,
                        protection_state="pending",
                        protection_quantity=None,
                        stop_price=signal.proposal.stop_price,
                        fill_price=None,
                        client_order_id=client_id,
                        protective_order_id=None,
                        entry_order_id=broker_order_id,
                        metadata={
                            "requested_quantity": order_quantity,
                            "submitted_quantity": order_quantity,
                            "reconciliation_status": reconciliation_status,
                            "order_status": sync.get("order_status"),
                            "strategy_version": signal.proposal.source,
                            "model_version": manifest_payload["model_version"],
                            "proposal_stop": signal.proposal.stop_price,
                            "proposal_entry": signal.proposal.entry_price,
                        },
                    )
                ledger.save_entry_manifest(
                    manifest_id=manifest_id,
                    created_at=now,
                    broker=broker,
                    environment=manifest_payload["environment"],
                    pillar=pillar,
                    canonical_symbol=manifest_payload["canonical_symbol"],
                    broker_symbol=manifest_payload["broker_symbol"],
                    side=signal.proposal.side.value,
                    model_version=manifest_payload["model_version"],
                    strategy_version=signal.proposal.source,
                    confidence=signal.proposal.confidence,
                    regime=manifest_payload["regime"],
                    approved_entry=signal.proposal.entry_price,
                    requested_quantity=order_quantity,
                    approved_notional=order_quantity * signal.proposal.entry_price,
                    approved_stop=signal.proposal.stop_price,
                    approved_target=None,
                    approved_dollar_risk=decision.max_loss_dollars,
                    allocation_at_approval=pillar_notional,
                    portfolio_risk_at_approval=gross,
                    risk_engine_decision=decision.reason,
                    lifecycle_state=(
                        "reconciled"
                        if reconciliation_status in {"exact_match", "fractional_reconciliation", "broker_confirmed"}
                        else reconciliation_status
                    ),
                    client_order_id_namespace=client_id,
                    fingerprint=manifest_payload["fingerprint"],
                    broker_order_id=broker_order_id,
                    submitted_quantity=order_quantity,
                    filled_quantity=sync.get("quantity"),
                    broker_confirmed_position_quantity=sync.get("quantity"),
                    average_fill_price=sync.get("average_price"),
                    reconciliation_status=reconciliation_status,
                    reconciliation_difference=sync.get("reconciliation_difference"),
                    metadata={"fill_sync": sync},
                )
                if sync.get("quantity") is None:
                    failures.append(
                        {
                            "symbol": signal.instrument.symbol,
                            "broker": broker,
                            "quantity": order_quantity,
                            "message": (
                                "broker order has not yet reconciled to a visible position; "
                                "retry later without resubmitting"
                            ),
                            "details": sync,
                        }
                    )
                    continue
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
                        ledger.save_entry_manifest(
                            manifest_id=manifest_id,
                            created_at=now,
                            broker=broker,
                            environment=manifest_payload["environment"],
                            pillar=pillar,
                            canonical_symbol=manifest_payload["canonical_symbol"],
                            broker_symbol=manifest_payload["broker_symbol"],
                            side=signal.proposal.side.value,
                            model_version=manifest_payload["model_version"],
                            strategy_version=signal.proposal.source,
                            confidence=signal.proposal.confidence,
                            regime=manifest_payload["regime"],
                            approved_entry=signal.proposal.entry_price,
                            requested_quantity=order_quantity,
                            approved_notional=order_quantity * signal.proposal.entry_price,
                            approved_stop=signal.proposal.stop_price,
                            approved_target=None,
                            approved_dollar_risk=decision.max_loss_dollars,
                            allocation_at_approval=pillar_notional,
                            portfolio_risk_at_approval=gross,
                            risk_engine_decision=decision.reason,
                            lifecycle_state="unprotected_position",
                            client_order_id_namespace=client_id,
                            fingerprint=manifest_payload["fingerprint"],
                            broker_order_id=broker_order_id,
                            submitted_quantity=order_quantity,
                            filled_quantity=sync["quantity"],
                            broker_confirmed_position_quantity=sync["quantity"],
                            average_fill_price=sync["average_price"],
                            reconciliation_status=str(sync.get("reconciliation_status") or "broker_confirmed"),
                            reconciliation_difference=sync.get("reconciliation_difference"),
                            protection_state="failed",
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
                            "model_version": manifest_payload["model_version"],
                            "proposal_stop": signal.proposal.stop_price,
                            "proposal_entry": signal.proposal.entry_price,
                        },
                    )
                    ledger.save_entry_manifest(
                        manifest_id=manifest_id,
                        created_at=now,
                        broker=broker,
                        environment=manifest_payload["environment"],
                        pillar=pillar,
                        canonical_symbol=manifest_payload["canonical_symbol"],
                        broker_symbol=manifest_payload["broker_symbol"],
                        side=signal.proposal.side.value,
                        model_version=manifest_payload["model_version"],
                        strategy_version=signal.proposal.source,
                        confidence=signal.proposal.confidence,
                        regime=manifest_payload["regime"],
                        approved_entry=signal.proposal.entry_price,
                        requested_quantity=order_quantity,
                        approved_notional=order_quantity * signal.proposal.entry_price,
                        approved_stop=signal.proposal.stop_price,
                        approved_target=None,
                        approved_dollar_risk=decision.max_loss_dollars,
                        allocation_at_approval=pillar_notional,
                        portfolio_risk_at_approval=gross,
                        risk_engine_decision=decision.reason,
                        lifecycle_state="active",
                        client_order_id_namespace=client_id,
                        fingerprint=manifest_payload["fingerprint"],
                        broker_order_id=broker_order_id,
                        submitted_quantity=order_quantity,
                        filled_quantity=sync["quantity"],
                        broker_confirmed_position_quantity=sync["quantity"],
                        average_fill_price=sync["average_price"],
                        reconciliation_status=str(sync.get("reconciliation_status") or "broker_confirmed"),
                        reconciliation_difference=sync.get("reconciliation_difference"),
                        protection_order_id=protective_order_id,
                        protection_quantity=abs(float(sync["quantity"])),
                        protection_stop=signal.proposal.stop_price,
                        protection_state="confirmed",
                        metadata={"protection_order": protection.details},
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
                **crypto_reconciliation_telemetry,
                "crypto_data_diagnostics": self.crypto_data_diagnostics,
                "crypto_data_valid": len(self.crypto_data_diagnostics.get("crypto_data_valid", [])),
                "crypto_data_invalid": len(self.crypto_data_diagnostics.get("crypto_data_invalid", [])),
                "risk_rejections": rejections,
                "submission_failures": failures,
                "duplicate_skips": duplicates,
                "sizing_skips": sizing,
                "top_candidates": diagnostics[:10],
                "pillar_allocations": PILLAR_ALLOCATIONS,
                "learned_parameters": learned,
                "position_management": position_management,
                "stale_orders": stale_orders,
            },
        )

    def _strategy_portfolio(self, portfolio: PortfolioState, ledger: PortfolioLedger | None = None) -> PortfolioState:
        manifest_symbols: set[str] = set()
        if ledger is not None:
            manifest_symbols = {
                str(manifest.get("canonical_symbol") or "").upper()
                for manifest in ledger.unresolved_entry_manifests()
                if str(manifest.get("created_at") or "") >= self.experiment_baseline_start.isoformat()
            }
        strategy_positions = {
            symbol: position
            for symbol, position in portfolio.positions.items()
            if position_is_experiment_eligible(position.opened_at, self.experiment_baseline_start)
            or symbol.upper() in manifest_symbols
        }
        deployed = sum(abs(position.quantity * position.average_price) for position in strategy_positions.values())
        cash = max(self.config.initial_equity - deployed, 0.0)
        return PortfolioState(
            equity=max(self.config.initial_equity, cash + deployed),
            cash=cash,
            daily_pnl=0.0,
            weekly_pnl=0.0,
            positions=strategy_positions,
        )

    def _load_histories(self, now: datetime):
        start = now - timedelta(days=max(self.config.lookback_days, 2))
        histories = {}
        etfs = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV"}
        provider_crypto = tuple(symbol for symbol in alpaca_crypto_universe() if symbol.endswith("/USD"))
        self.provider_crypto_universe = provider_crypto
        crypto_symbols = tuple(dict.fromkeys((*self.config.crypto_universe, *provider_crypto)))
        instruments = [
            *(Instrument(s, AssetClass.ETF if s in etfs else AssetClass.STOCK) for s in self.config.alpaca_universe),
            *(Instrument(s, AssetClass.FOREX) for s in self.config.oanda_universe),
            *(Instrument(s, AssetClass.CRYPTO) for s in crypto_symbols),
        ]
        diagnostics = {"crypto_universe": [], "crypto_data_valid": [], "crypto_data_invalid": [], "errors": {}}
        for instrument in instruments:
            if instrument.asset_class is AssetClass.CRYPTO:
                diagnostics["crypto_universe"].append(instrument.symbol)
            try:
                bars = self.feed.history(instrument, start, now, interval=self.config.interval)
            except Exception as exc:
                if instrument.asset_class is AssetClass.CRYPTO:
                    diagnostics["crypto_data_invalid"].append(instrument.symbol)
                    diagnostics["errors"][instrument.symbol] = f"{type(exc).__name__}: {exc}"
                continue
            if len(bars) >= 20:
                histories[instrument] = bars
                if instrument.asset_class is AssetClass.CRYPTO:
                    diagnostics["crypto_data_valid"].append(instrument.symbol)
            elif instrument.asset_class is AssetClass.CRYPTO:
                diagnostics["crypto_data_invalid"].append(instrument.symbol)
                diagnostics["errors"][instrument.symbol] = f"insufficient_history:{len(bars)}/20"
        diagnostics.update({
            "crypto_scanned": len(diagnostics["crypto_universe"]),
            "crypto_data_valid_count": len(diagnostics["crypto_data_valid"]),
            "crypto_data_invalid_count": len(diagnostics["crypto_data_invalid"]),
            "interval": self.config.interval,
            "lookback_days": self.config.lookback_days,
        })
        self.crypto_data_diagnostics = diagnostics
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

    def _manage_crypto_positions(self, portfolio: PortfolioState, histories, ledger: PortfolioLedger | None = None) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Re-evaluate every open Crypto position before considering new entries.

        This is deliberately conservative: a missing or weak re-entry signal is
        evidence for telemetry, not an automatic liquidation. Exits require a
        clear invalidation (no usable market candidate), while stops/targets
        continue through the existing guarded exit coordinator.
        """
        decisions: list[dict[str, object]] = []
        exits: list[dict[str, object]] = []
        history_by_symbol = {item.symbol.replace("/", "").upper(): (item, bars) for item, bars in histories.items()}
        for symbol, position in portfolio.positions.items():
            if position.asset_class is not AssetClass.CRYPTO:
                continue
            instrument, bars = history_by_symbol.get(symbol.replace("/", "").upper(), (None, None))
            candidate = self.scanner.score_instrument(instrument, bars) if instrument and bars else None
            signal = choose_experimental_long_signal(
                instrument, bars, scanner=self.scanner, strategies=self.strategies, config=self.experiment
            ) if instrument and bars else None
            edge = signal.edge if signal else None
            original = ledger.latest_unresolved_entry_manifest_for_symbol(symbol, broker="alpaca-crypto-paper") if ledger else None
            original_strategy = str(original.get("strategy_version") or "unknown") if original else "unknown"
            original_edge = (original.get("metadata") or {}).get("edge") if original else None
            thesis_valid = signal is not None
            edge_valid = edge is not None and edge.expected_net_edge > edge.required_edge
            deterioration = candidate is None or (not thesis_valid and not edge_valid)
            if deterioration:
                self._crypto_exit_confirmations[symbol] = self._crypto_exit_confirmations.get(symbol, 0) + 1
            else:
                self._crypto_exit_confirmations[symbol] = 0
            confirmed = self._crypto_exit_confirmations.get(symbol, 0) >= self.config.crypto_exit_confirmation_cycles
            if candidate is None and confirmed:
                decision, reason = "EXIT_SIGNAL_INVALIDATED", "fresh data no longer supports the original BUY thesis"
            elif not thesis_valid and not edge_valid and confirmed:
                decision, reason = "EXIT_EDGE_GONE", "current expected net edge is absent or below required edge"
            elif edge_valid:
                decision, reason = "HOLD_EDGE_POSITIVE", "current strategy retains positive cost-aware edge"
            elif deterioration:
                decision, reason = "TIGHTEN_PROTECTION", f"thesis/edge deterioration confirmation {self._crypto_exit_confirmations[symbol]}/{self.config.crypto_exit_confirmation_cycles}"
            else:
                decision, reason = "HOLD_THESIS_VALID", "original strategy thesis remains supported"
            row = {
                "symbol": symbol, "decision": decision, "reason": reason,
                "current_price": candidate.last_price if candidate else None,
                "momentum_pct": candidate.momentum_pct if candidate else None,
                "score": candidate.score if candidate else None,
                "strategy": signal.proposal.source if signal else None,
                "lane": signal.mode if signal else "POSITION_MANAGEMENT",
                "current_edge": edge.as_dict() if edge else None,
                "capital": abs(position.quantity * position.average_price),
                "original_strategy": original_strategy,
                "original_edge": original_edge,
                "thesis_valid": thesis_valid,
                "edge_valid": edge_valid,
                "would_open_today": signal is not None,
                "confirmation_cycles": self._crypto_exit_confirmations.get(symbol, 0),
                "holding_horizon_valid": True,
            }
            decisions.append(row)
            self.experiment_ledger.record_decision(
                pillar="alpaca_crypto", symbol=symbol, strategy=str(row["strategy"] or "position_management"),
                timeframe=self.config.interval, lane=str(row["lane"]), decision=decision,
                entry_price=position.average_price, edge=edge,
                features={"reason": reason, "score": row["score"], "momentum_pct": row["momentum_pct"]},
            )
            if decision in {"EXIT_SIGNAL_INVALIDATED", "EXIT_EDGE_GONE"}:
                result = AlpacaCryptoExitCoordinator(
                    AlpacaCryptoExitPaperBroker.from_env(), self.idempotency, ledger_path=self.config.ledger_path
                ).close(symbol, stop_price=position.stop_price)
                exits.append({"symbol": symbol, "decision": decision, "reason": reason, "ok": result.ok, "message": result.message})
        return decisions, exits

    def _cancel_stale_crypto_orders(self, ledger: PortfolioLedger, now: datetime) -> list[dict[str, object]]:
        actions: list[dict[str, object]] = []
        for manifest in ledger.unresolved_entry_manifests(broker="alpaca-crypto-paper"):
            if str(manifest.get("lifecycle_state")) not in {"order_pending", "order_submitted"}:
                continue
            created = str(manifest.get("created_at") or "")
            try:
                age = max((now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds(), 0.0)
            except ValueError:
                continue
            # Market orders have a short execution SLA; limit orders retain
            # the longer working window.  Provider state is rechecked by the
            # guarded cancellation coordinator before any action is taken.
            order_type = str(manifest.get("order_type") or "market").lower()
            symbol = str(manifest.get("canonical_symbol") or "")
            time_in_force = str(manifest.get("time_in_force") or "gtc").lower()
            broker_order_id = str(manifest.get("broker_order_id") or "")
            if order_type == "market" and broker_order_id:
                terminal = alpaca_paper_order_status(broker_order_id)
                status = str(terminal.details.get("status") or "").lower()
                if terminal.ok and status in {"canceled", "expired", "rejected", "filled", "partially_filled"}:
                    outcome = {"canceled": "canceled", "expired": "expired", "rejected": "rejected", "filled": "filled", "partially_filled": "partial"}[status]
                    _record_crypto_execution_quality(symbol, outcome, order_id=broker_order_id, order_type=order_type, time_in_force=time_in_force, age_seconds=age)
                    ledger.mark_manifest_terminal(
                        str(manifest.get("manifest_id")),
                        lifecycle_state=f"{status}_unfilled" if status in {"canceled", "expired", "rejected"} else "reconciled",
                        metadata={"provider_terminal_status": status, "provider_order": terminal.details},
                    )
                    actions.append({"symbol": symbol, "age_seconds": age, "action": "RECONCILE_TERMINAL", "status": status})
                    continue
            stale_window = self.config.crypto_market_order_seconds if order_type == "market" else self.config.crypto_stale_order_seconds
            if age < stale_window:
                continue
            result = cancel_alpaca_open_orders_for_symbol(symbol)
            cancelled = list(result.details.get("cancelled_order_ids", []))
            if cancelled:
                _record_crypto_execution_quality(symbol, "stale", age_seconds=age)
                _record_crypto_execution_quality(symbol, "canceled", age_seconds=age)
                ledger.mark_manifest_terminal(
                    str(manifest.get("manifest_id")), lifecycle_state="cancelled_unfilled",
                    metadata={"stale_order": True, "order_type": order_type, "age_seconds": age, "stale_window_seconds": stale_window, "cancelled_order_ids": cancelled, "reason": "provider accepted but did not fill within order-type stale window"},
                )
            actions.append({"symbol": symbol, "age_seconds": age, "action": "CANCEL_STALE" if cancelled else "KEEP_WORKING", "order_ids": cancelled})
        return actions

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
        broker_symbols = {
            p.symbol.replace("/", "").upper()
            for p in [*alpaca, *oanda]
            if abs(p.quantity) > 1e-12
        }
        changed = False
        for symbol in list(portfolio.positions):
            if symbol.replace("/", "").upper() not in broker_symbols:
                del portfolio.positions[symbol]
                changed = True
        if changed:
            ledger.save_portfolio(portfolio, peak_equity=peak)
