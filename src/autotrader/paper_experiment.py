from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import AssetClass, ScanCandidate, TradeProposal


@dataclass(frozen=True)
class PaperExperimentConfig:
    enabled: bool
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
        return cls(enabled=requested and safe)

    def assert_safe(self, *, live_trading_enabled: bool, provider_environment: str, endpoint: str) -> None:
        if self.enabled and (live_trading_enabled or provider_environment.lower() != "paper" or "paper-api.alpaca.markets" not in endpoint.lower()):
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

    def record_decision(self, *, pillar: str, symbol: str, strategy: str, timeframe: str, lane: str, decision: str, entry_price: float | None, edge: EdgeEstimate | None, features: dict[str, object]) -> int:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT INTO experiment_decisions (occurred_at,pillar,symbol,strategy,timeframe,lane,decision,entry_price,edge_json,features_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(UTC).isoformat(), pillar, symbol, strategy, timeframe, lane, decision, entry_price, json.dumps(edge.as_dict() if edge else {}), json.dumps(features, default=str)),
            )
            return int(cursor.lastrowid)

    def record_outcome(self, decision_id: int, outcome: dict[str, object]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE experiment_decisions SET outcome_json=? WHERE id=?", (json.dumps(outcome, default=str), decision_id))


def experimental_position_quantity_cap(*, pillar_capital: float, entry_price: float, config: PaperExperimentConfig) -> float:
    if pillar_capital <= 0 or entry_price <= 0:
        return 0.0
    return pillar_capital * config.experimental_position_cap_pct / entry_price


def estimate_edge(candidate: ScanCandidate, proposal: TradeProposal, *, asset_class: AssetClass, experimental: bool) -> EdgeEstimate:
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


def experimental_candidate(candidate: ScanCandidate, proposals: tuple[TradeProposal | None, ...], *, config: PaperExperimentConfig) -> tuple[TradeProposal, EdgeEstimate] | None:
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
