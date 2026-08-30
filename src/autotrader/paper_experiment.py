from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import AssetClass, ScanCandidate, TradeProposal

COUNTERFACTUAL_HORIZONS_MINUTES = (1, 3, 5, 10, 15, 30, 60)
COUNTERFACTUAL_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PaperExperimentConfig:
    enabled: bool
    micro_trading: bool = False
    short_experiment: bool = False
    derivatives_research: bool = False
    arbitrage_research: bool = False
    baseline_required_edge: float = 0.005
    experimental_required_edge: float = 0.0025
    experimental_risk_scale: float = 0.50
    experimental_max_pillar_utilization: float = 0.75
    experimental_position_cap_pct: float = 0.20
    crypto_fee_bps: float = 10.0
    crypto_slippage_bps: float = 10.0
    crypto_spread_bps: float = 20.0
    metals_fee_bps: float = 5.0
    metals_slippage_bps: float = 5.0
    metals_spread_bps: float = 10.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PaperExperimentConfig:
        env = os.environ if environ is None else environ
        requested = env.get("PAPER_EXPERIMENT_MODE", "false").strip().lower() == "true"
        live = env.get("LIVE_TRADING_ENABLED", "false").strip().lower()
        alpaca = env.get("ALPACA_ENV", "paper").strip().lower()
        endpoint = env.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets").strip().lower()
        safe = live == "false" and alpaca == "paper" and "paper-api.alpaca.markets" in endpoint
        return cls(
            enabled=requested and safe,
            micro_trading=env.get("MICRO_TRADING_EXPERIMENT_MODE", "false").strip().lower() == "true" and safe,
            short_experiment=env.get("SHORT_EXPERIMENT_MODE", "false").strip().lower() == "true" and safe,
            derivatives_research=env.get("DERIVATIVES_RESEARCH_MODE", "false").strip().lower() == "true" and safe,
            arbitrage_research=env.get("ARBITRAGE_RESEARCH_MODE", "false").strip().lower() == "true" and safe,
        )

    def assert_safe(self, *, live_trading_enabled: bool, provider_environment: str, endpoint: str) -> None:
        if self.enabled and (
            live_trading_enabled
            or provider_environment.lower() != "paper"
            or "paper-api.alpaca.markets" not in endpoint.lower()
        ):
            raise RuntimeError("PAPER_EXPERIMENT_MODE requires LIVE_TRADING_ENABLED=false and Alpaca PAPER")


@dataclass(frozen=True)
class EdgeEstimate:
    expected_gross_move: float
    spread_cost: float
    fee_cost: float
    slippage_cost: float
    volatility: float
    stop_distance: float
    expected_reward: float
    expected_downside: float
    expected_net_edge: float
    expected_reward_to_risk: float
    required_edge: float
    assumptions: dict[str, float | str]

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class PaperExperimentLedger:
    """Durable champion/challenger decision log; never used as an order gate."""

    def __init__(self, path: str | Path = "var/autotrader/paper_experiment.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS experiment_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    entry_price REAL,
                    edge_json TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    outcome_json TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS counterfactual_observations (
                    observation_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    champion_decision TEXT NOT NULL,
                    challenger_decision TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    stop_price REAL,
                    target_price REAL,
                    features_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'PENDING_OUTCOME',
                    outcomes_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS activity_observations (
                    experiment_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    provider TEXT,
                    market TEXT NOT NULL,
                    asset_class TEXT,
                    strategy TEXT NOT NULL,
                    strategy_version TEXT,
                    model_version TEXT,
                    timeframe TEXT,
                    market_regime TEXT,
                    features_json TEXT NOT NULL,
                    signal_direction TEXT,
                    raw_score REAL,
                    normalized_confidence REAL,
                    estimated_edge REAL,
                    expected_value REAL,
                    candidate_status TEXT NOT NULL,
                    qualification_result TEXT,
                    rejection_reason TEXT,
                    risk_decision TEXT,
                    position_sizing_json TEXT,
                    available_capital REAL,
                    existing_exposure REAL,
                    correlation_exposure REAL,
                    order_id TEXT,
                    provider_order_id TEXT,
                    fill_id TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    quantity REAL,
                    fees REAL,
                    slippage REAL,
                    realized_pnl REAL,
                    unrealized_pnl REAL,
                    holding_period_seconds REAL,
                    exit_reason TEXT,
                    result_classification TEXT,
                    learning_update TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS shadow_trades (
                    shadow_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    hypothetical_entry REAL NOT NULL,
                    entry_at TEXT NOT NULL,
                    entry_reason TEXT NOT NULL,
                    qualification_score REAL,
                    prevented_by_threshold TEXT,
                    hypothetical_stop REAL,
                    hypothetical_target REAL,
                    hypothetical_exit REAL,
                    exit_at TEXT,
                    hypothetical_pnl REAL,
                    mfe REAL,
                    mae REAL,
                    result TEXT,
                    exit_reason TEXT,
                    regime TEXT,
                    CHECK (shadow_id <> '')
                )"""
            )
            # Forward-compatible schema repair for databases created before
            # shadow exit attribution was introduced.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(shadow_trades)")}
            if "exit_reason" not in columns:
                connection.execute("ALTER TABLE shadow_trades ADD COLUMN exit_reason TEXT")

    def record_decision(
        self,
        *,
        pillar: str,
        symbol: str,
        strategy: str,
        timeframe: str,
        lane: str,
        decision: str,
        entry_price: float | None,
        edge: EdgeEstimate | None,
        features: dict[str, object],
        experiment_id: str | None = None,
    ) -> int:
        experiment_id = experiment_id or f"EXP-{uuid.uuid4().hex}"
        occurred_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT INTO experiment_decisions (occurred_at,pillar,symbol,strategy,timeframe,lane,decision,entry_price,edge_json,features_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    occurred_at,
                    pillar,
                    symbol,
                    strategy,
                    timeframe,
                    lane,
                    decision,
                    entry_price,
                    json.dumps(edge.as_dict() if edge else {}),
                    json.dumps(features, default=str),
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO activity_observations
                (experiment_id,occurred_at,pillar,engine,market,strategy,timeframe,features_json,
                 candidate_status,qualification_result,rejection_reason,risk_decision,entry_price)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    experiment_id,
                    occurred_at,
                    pillar,
                    pillar,
                    symbol,
                    strategy,
                    timeframe,
                    json.dumps(features, default=str),
                    "DECISION",
                    decision,
                    decision if decision not in {"QUALIFIED", "APPROVED", "TRADE"} else None,
                    decision,
                    entry_price,
                ),
            )
            return int(cursor.lastrowid)

    def record_activity(self, **observation: object) -> str:
        """Persist a complete funnel observation without creating a broker order."""
        experiment_id = str(observation.get("experiment_id") or f"EXP-{uuid.uuid4().hex}")
        occurred_at = str(observation.get("timestamp") or datetime.now(UTC).isoformat())
        columns = {
            "experiment_id": experiment_id,
            "occurred_at": occurred_at,
            "pillar": observation.get("pillar", "UNKNOWN"),
            "engine": observation.get("engine", "UNKNOWN"),
            "provider": observation.get("provider"),
            "market": observation.get("market", "UNKNOWN"),
            "asset_class": observation.get("asset_class"),
            "strategy": observation.get("strategy", "UNKNOWN"),
            "strategy_version": observation.get("strategy_version"),
            "model_version": observation.get("model_version"),
            "timeframe": observation.get("timeframe"),
            "market_regime": observation.get("market_regime"),
            "features_json": json.dumps(observation.get("features", {}), default=str),
            "signal_direction": observation.get("signal_direction"),
            "raw_score": observation.get("raw_score"),
            "normalized_confidence": observation.get("normalized_confidence"),
            "estimated_edge": observation.get("estimated_edge"),
            "expected_value": observation.get("expected_value"),
            "candidate_status": observation.get("candidate_status", "OBSERVED"),
            "qualification_result": observation.get("qualification_result"),
            "rejection_reason": observation.get("rejection_reason"),
            "risk_decision": observation.get("risk_decision"),
            "position_sizing_json": json.dumps(observation.get("position_sizing", {}), default=str),
            "available_capital": observation.get("available_capital"),
            "existing_exposure": observation.get("existing_exposure"),
            "correlation_exposure": observation.get("correlation_exposure"),
            "order_id": observation.get("order_id"),
            "provider_order_id": observation.get("provider_order_id"),
            "fill_id": observation.get("fill_id"),
            "entry_price": observation.get("entry_price"),
            "exit_price": observation.get("exit_price"),
            "quantity": observation.get("quantity"),
            "fees": observation.get("fees"),
            "slippage": observation.get("slippage"),
            "realized_pnl": observation.get("realized_pnl"),
            "unrealized_pnl": observation.get("unrealized_pnl"),
            "holding_period_seconds": observation.get("holding_period_seconds"),
            "exit_reason": observation.get("exit_reason"),
            "result_classification": observation.get("result_classification"),
            "learning_update": observation.get("learning_update"),
        }
        names = ",".join(columns)
        placeholders = ",".join("?" for _ in columns)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                f"INSERT OR IGNORE INTO activity_observations ({names}) VALUES ({placeholders})",
                tuple(columns.values()),
            )
        return experiment_id

    def backfill_activity_observations(self) -> int:
        """Make pre-V1 decision rows visible in the unified funnel once."""
        inserted = 0
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id,occurred_at,pillar,symbol,strategy,timeframe,decision,entry_price,features_json FROM experiment_decisions"
            ).fetchall()
            for row in rows:
                before = connection.total_changes
                connection.execute(
                    """INSERT OR IGNORE INTO activity_observations
                    (experiment_id,occurred_at,pillar,engine,market,strategy,timeframe,features_json,
                     candidate_status,qualification_result,rejection_reason,risk_decision,entry_price)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"EXP-LEGACY-{row[0]}", row[1], row[2], row[2], row[3], row[4], row[5], row[8] or "{}",
                        "DECISION", row[6], row[6], row[6], row[7],
                    ),
                )
                inserted += connection.total_changes - before
        return inserted

    def record_shadow_trade(self, *, shadow_id: str, experiment_id: str, pillar: str, strategy_id: str,
                            market: str, direction: str, hypothetical_entry: float, entry_at: str,
                            entry_reason: str, qualification_score: float | None = None,
                            prevented_by_threshold: str | None = None, hypothetical_stop: float | None = None,
                            hypothetical_target: float | None = None, regime: str | None = None) -> str:
        """Persist a research-only trade; this method has no broker or P&L side effects."""
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO shadow_trades
                (shadow_id,experiment_id,pillar,strategy_id,market,direction,hypothetical_entry,entry_at,
                 entry_reason,qualification_score,prevented_by_threshold,hypothetical_stop,hypothetical_target,regime)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (shadow_id, experiment_id, pillar, strategy_id, market, direction, hypothetical_entry, entry_at,
                 entry_reason, qualification_score, prevented_by_threshold, hypothetical_stop, hypothetical_target, regime),
            )
        return shadow_id

    def settle_shadow_trades(
        self,
        bars_by_symbol: dict[str, list[object]],
        *,
        now: datetime | None = None,
        time_stop_minutes: int = 60,
    ) -> dict[str, int]:
        """Settle open shadow trades using only bars available after entry.

        This is research-only accounting: it never calls a broker and never
        changes portfolio, capital, or realized P&L state.
        """
        if time_stop_minutes <= 0:
            raise ValueError("time stop must be positive")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        counts = {"closed": 0, "insufficient_data": 0, "open": 0}
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT shadow_id,market,direction,hypothetical_entry,entry_at,hypothetical_stop,hypothetical_target "
                "FROM shadow_trades WHERE exit_at IS NULL"
            ).fetchall()
            for shadow_id, market, direction, entry, entry_at, stop, target in rows:
                if direction not in {"BUY", "SELL"}:
                    counts["insufficient_data"] += 1
                    continue
                opened = datetime.fromisoformat(str(entry_at).replace("Z", "+00:00")).astimezone(UTC)
                bars = sorted(
                    (bar for bar in bars_by_symbol.get(str(market), []) if getattr(bar, "timestamp", None)),
                    key=lambda bar: bar.timestamp,
                )
                def bar_time(bar: object) -> datetime:
                    timestamp = bar.timestamp
                    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
                forward = [bar for bar in bars if opened < bar_time(bar) <= current]
                if not forward:
                    counts["open"] += 1
                    continue
                exit_bar = None
                reason = None
                for bar in forward:
                    if direction == "BUY":
                        stop_hit = stop is not None and bar.low <= stop
                        target_hit = target is not None and bar.high >= target
                    else:
                        stop_hit = stop is not None and bar.high >= stop
                        target_hit = target is not None and bar.low <= target
                    # Conservative same-bar ordering: stop wins when both
                    # levels are touched because intrabar order is unknown.
                    if stop_hit:
                        exit_bar, reason = bar, "STOP_LOSS"
                        break
                    if target_hit:
                        exit_bar, reason = bar, "TARGET"
                        break
                    if bar_time(bar) >= opened + timedelta(minutes=time_stop_minutes):
                        exit_bar, reason = bar, "TIME_STOP"
                        break
                if exit_bar is None:
                    counts["open"] += 1
                    continue
                prices = [float(bar.low if direction == "BUY" else bar.high) for bar in forward]
                favorable = [float(bar.high if direction == "BUY" else bar.low) for bar in forward]
                pnl = (float(exit_bar.close) - float(entry)) if direction == "BUY" else (float(entry) - float(exit_bar.close))
                mfe = (max(favorable) - float(entry)) if direction == "BUY" else (float(entry) - min(favorable))
                mae = (min(prices) - float(entry)) if direction == "BUY" else (float(entry) - max(prices))
                result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
                connection.execute(
                    "UPDATE shadow_trades SET hypothetical_exit=?,exit_at=?,hypothetical_pnl=?,mfe=?,mae=?,result=?,exit_reason=? WHERE shadow_id=? AND exit_at IS NULL",
                    (float(exit_bar.close), bar_time(exit_bar).isoformat(), pnl, mfe, mae, result, reason, shadow_id),
                )
                counts["closed"] += 1
        return counts

    def record_outcome(self, decision_id: int, outcome: dict[str, object]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE experiment_decisions SET outcome_json=? WHERE id=?",
                (json.dumps(outcome, default=str), decision_id),
            )

    def record_counterfactual(
        self,
        *,
        symbol: str,
        occurred_at: datetime,
        champion_decision: str,
        challenger_decision: str,
        entry_price: float,
        quantity: float,
        stop_price: float | None,
        target_price: float | None,
        features: dict[str, object],
        candidate_identity: str,
    ) -> str:
        """Insert one deduplicated research observation; never a broker trade."""
        bucket = occurred_at.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
        observation_id = (
            __import__("hashlib")
            .sha256(
                f"five_pillar_baseline_v1|paper_experiment_challenger_v1|{symbol}|{bucket}|{candidate_identity}".encode()
            )
            .hexdigest()[:32]
        )
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO counterfactual_observations
                (observation_id,occurred_at,symbol,champion_decision,challenger_decision,
                 entry_price,quantity,stop_price,target_price,features_json,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id,
                    occurred_at.astimezone(UTC).isoformat(),
                    symbol,
                    champion_decision,
                    challenger_decision,
                    entry_price,
                    quantity,
                    stop_price,
                    target_price,
                    json.dumps(features, default=str),
                    now,
                ),
            )
        return observation_id

    def resolve_counterfactuals(
        self, bars_by_symbol: dict[str, list[object]], *, now: datetime | None = None
    ) -> dict[str, int]:
        """Resolve horizons from real bars; unavailable prices remain UNKNOWN."""
        now = (now or datetime.now(UTC)).astimezone(UTC)
        counts = {"evaluated": 0, "partially_evaluated": 0, "pending": 0, "insufficient_data": 0, "expired": 0}
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM counterfactual_observations WHERE state IN ('PENDING_OUTCOME','PARTIALLY_EVALUATED')"
            ).fetchall()
            for row in rows:
                (
                    oid,
                    occurred,
                    symbol,
                    champ,
                    chall,
                    entry,
                    qty,
                    stop,
                    target,
                    raw_features,
                    state,
                    raw_outcomes,
                    _updated,
                ) = row
                observed_at = datetime.fromisoformat(occurred.replace("Z", "+00:00")).astimezone(UTC)
                bars = sorted(bars_by_symbol.get(symbol, []), key=lambda bar: bar.timestamp)
                outcomes = json.loads(raw_outcomes or "{}")
                for minutes in COUNTERFACTUAL_HORIZONS_MINUTES:
                    key = str(minutes)
                    if key in outcomes:
                        continue
                    due = observed_at + timedelta(minutes=minutes)
                    if due > now:
                        continue
                    bar = next((candidate for candidate in bars if candidate.timestamp >= due), None)
                    if bar is None:
                        outcomes[key] = {"status": "UNKNOWN", "reason": "provider price history unavailable"}
                        continue
                    gross = (bar.close - entry) * qty
                    costs = abs(entry * qty) * float(json.loads(raw_features or "{}").get("estimated_cost_rate", 0.004))
                    outcomes[key] = {
                        "status": "EVALUATED",
                        "timestamp": bar.timestamp.isoformat(),
                        "gross_pnl": gross,
                        "estimated_costs": costs,
                        "net_pnl": gross - costs,
                        "mfe": (bar.high - entry) * qty,
                        "mae": (bar.low - entry) * qty,
                        "stop_hit": bool(stop and bar.low <= stop),
                        "target_hit": bool(target and bar.high >= target),
                        "price": bar.close,
                    }
                evaluable = [value for value in outcomes.values() if value.get("status") == "EVALUATED"]
                due_count = sum(
                    1 for minutes in COUNTERFACTUAL_HORIZONS_MINUTES if observed_at + timedelta(minutes=minutes) <= now
                )
                if len(outcomes) == len(COUNTERFACTUAL_HORIZONS_MINUTES):
                    new_state = "EVALUATED" if evaluable else "INSUFFICIENT_DATA"
                elif due_count >= len(COUNTERFACTUAL_HORIZONS_MINUTES) and not evaluable:
                    new_state = "INSUFFICIENT_DATA"
                elif evaluable:
                    new_state = "PARTIALLY_EVALUATED"
                elif now - observed_at > timedelta(days=COUNTERFACTUAL_RETENTION_DAYS):
                    new_state = "EXPIRED"
                else:
                    new_state = "PENDING_OUTCOME"
                connection.execute(
                    "UPDATE counterfactual_observations SET state=?, outcomes_json=?, updated_at=? WHERE observation_id=?",
                    (new_state, json.dumps(outcomes, default=str), now.isoformat(), oid),
                )
                counts[new_state.lower()] = counts.get(new_state.lower(), 0) + 1
        return counts

    def pending_counterfactual_symbols(self) -> list[str]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT symbol FROM counterfactual_observations WHERE state IN ('PENDING_OUTCOME','PARTIALLY_EVALUATED')"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def backfill_experimental_decisions(self) -> dict[str, int]:
        """Convert existing Challenger-only decisions into explicit research rows.

        The runtime only selected the experimental lane when Champion rejected
        the same candidate, so this preserves that recorded decision without
        claiming an order, fill, or outcome.
        """
        inserted = 0
        existing = 0
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id,occurred_at,symbol,entry_price,edge_json,features_json FROM experiment_decisions WHERE lane='EXPERIMENTAL_PAPER'"
            ).fetchall()
            for decision_id, occurred, symbol, entry, raw_edge, raw_features in rows:
                edge = json.loads(raw_edge or "{}")
                features = json.loads(raw_features or "{}")
                entry = float(entry or 0)
                if entry <= 0:
                    continue
                stop_distance = float(edge.get("stop_distance") or 0.005)
                stop = entry * max(1.0 - stop_distance, 0.0001)
                bucket = (
                    datetime.fromisoformat(str(occurred).replace("Z", "+00:00"))
                    .astimezone(UTC)
                    .replace(second=0, microsecond=0)
                    .isoformat()
                )
                candidate_identity = f"backfill-{decision_id}"
                observation_id = (
                    __import__("hashlib")
                    .sha256(
                        f"five_pillar_baseline_v1|paper_experiment_challenger_v1|{symbol}|{bucket}|{candidate_identity}".encode()
                    )
                    .hexdigest()[:32]
                )
                exists = connection.execute(
                    "SELECT 1 FROM counterfactual_observations WHERE observation_id=?", (observation_id,)
                ).fetchone()
                self.record_counterfactual(
                    symbol=str(symbol),
                    occurred_at=datetime.fromisoformat(str(occurred).replace("Z", "+00:00")),
                    champion_decision="REJECT",
                    challenger_decision="ACCEPT",
                    entry_price=entry,
                    quantity=1000.0 / entry,
                    stop_price=stop,
                    target_price=entry + 2 * (entry - stop),
                    features={
                        **features,
                        "challenger_edge": edge,
                        "tag": "COUNTERFACTUAL_ONLY",
                        "backfilled_from_decision_id": decision_id,
                    },
                    candidate_identity=candidate_identity,
                )
                if exists is None:
                    inserted += 1
                else:
                    existing += 1
        return {"inserted": inserted, "existing": existing}

    def counterfactual_summary(self) -> dict[str, object]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT champion_decision,challenger_decision,state,outcomes_json FROM counterfactual_observations"
            ).fetchall()
        summary = {
            "observations": len(rows),
            "evaluated": 0,
            "pending": 0,
            "partially_evaluated": 0,
            "insufficient_data": 0,
            "expired": 0,
            "champion": {"observations": 0, "accepts": 0, "pnl": 0.0, "wins": 0},
            "challenger": {"observations": 0, "accepts": 0, "pnl": 0.0, "wins": 0},
        }
        for champ, chall, state, raw in rows:
            key = state.lower()
            summary[key] = summary.get(key, 0) + 1
            outcomes = json.loads(raw or "{}")
            evaluated = [v for v in outcomes.values() if v.get("status") == "EVALUATED"]
            for name, decision in (("champion", champ), ("challenger", chall)):
                bucket = summary[name]
                bucket["observations"] += 1
                if decision == "ACCEPT":
                    bucket["accepts"] += 1
                if evaluated and decision == "ACCEPT":
                    pnl = evaluated[-1].get("net_pnl", 0.0)
                    bucket["pnl"] += pnl
                    bucket["wins"] += int(pnl > 0)
        for name in ("champion", "challenger"):
            bucket = summary[name]
            bucket["win_rate"] = bucket["wins"] / bucket["observations"] if bucket["observations"] else None
            bucket["expectancy"] = bucket["pnl"] / bucket["observations"] if bucket["observations"] else None
        return summary


def experimental_position_quantity_cap(
    *, pillar_capital: float, entry_price: float, config: PaperExperimentConfig
) -> float:
    if pillar_capital <= 0 or entry_price <= 0:
        return 0.0
    return pillar_capital * config.experimental_position_cap_pct / entry_price


def estimate_edge(
    candidate: ScanCandidate, proposal: TradeProposal, *, asset_class: AssetClass, experimental: bool
) -> EdgeEstimate:
    if asset_class is AssetClass.CRYPTO:
        spread_bps, fee_bps, slippage_bps = 20.0, 10.0, 10.0
    else:
        spread_bps, fee_bps, slippage_bps = 10.0, 5.0, 5.0
    volatility = max(candidate.average_range_pct / 100.0, 0.0001)
    expected_gross = max(abs(candidate.momentum_pct) / 100.0, volatility * (1.25 if experimental else 1.5))
    costs = (spread_bps + fee_bps + slippage_bps) / 10000.0
    stop_distance = proposal.risk_per_unit / proposal.entry_price
    expected_reward = expected_gross
    expected_downside = max(stop_distance, volatility)
    net = expected_reward - costs
    required = 0.0025 if experimental else 0.005
    return EdgeEstimate(
        expected_gross_move=expected_gross,
        spread_cost=spread_bps / 10000.0,
        fee_cost=fee_bps / 10000.0,
        slippage_cost=slippage_bps / 10000.0,
        volatility=volatility,
        stop_distance=stop_distance,
        expected_reward=expected_reward,
        expected_downside=expected_downside,
        expected_net_edge=net,
        expected_reward_to_risk=expected_reward / expected_downside if expected_downside > 0 else 0.0,
        required_edge=required,
        assumptions={
            "cost_units": "decimal_return",
            "spread_bps": spread_bps,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "fee_source": "conservative_paper_assumption_until_provider_fee_available",
        },
    )


def experimental_candidate(
    candidate: ScanCandidate, proposals: tuple[TradeProposal | None, ...], *, config: PaperExperimentConfig
) -> tuple[TradeProposal, EdgeEstimate] | None:
    buys = [proposal for proposal in proposals if proposal is not None and proposal.side.value == "buy"]
    if not buys or candidate.score < 5.0:
        return None
    # A mean-reversion BUY is independent of directional momentum. This is the
    # deliberate challenger exception to the baseline long-momentum veto.
    ordered = sorted(buys, key=lambda proposal: (proposal.source != "mean_reversion", -proposal.confidence))
    for proposal in ordered:
        edge = estimate_edge(candidate, proposal, asset_class=proposal.asset_class, experimental=True)
        if edge.expected_net_edge > edge.required_edge and edge.expected_reward_to_risk > 1.0:
            return proposal, edge
    return None
