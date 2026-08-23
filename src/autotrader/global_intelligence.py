"""Paper-only cross-pillar intelligence, hedge, cash, and counterfactual primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable, Mapping

from .capital_allocations import SIX_PILLARS


def _number(value: object, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if isfinite(value) else default


@dataclass(frozen=True)
class Opportunity:
    pillar: str
    engine: str
    instrument: str
    direction: str
    expected_return: float
    expected_edge: float
    confidence: float
    risk: float
    liquidity: float
    spread: float
    fees: float
    capital_required: float
    time_horizon: str = "unknown"
    regime: str = "unknown"
    correlation_impact: float = 0.0
    hedging_value: float = 0.0
    data_quality: float = 0.0
    model_quality: float = 0.0
    execution_uncertainty: float = 1.0

    @property
    def score(self) -> float:
        return ((self.expected_edge * max(self.confidence, 0.0) * max(self.data_quality, 0.0)
                 * max(self.model_quality, 0.0)) + self.hedging_value * 0.25
                - self.risk * 0.5 - self.spread - self.fees - self.execution_uncertainty * 0.1
                - max(self.correlation_impact, 0.0) * 0.1)


def rank_opportunities(opportunities: Iterable[Opportunity], *, available_cash: float) -> list[Opportunity]:
    return sorted((item for item in opportunities if item.capital_required <= available_cash),
                  key=lambda item: item.score, reverse=True)


@dataclass(frozen=True)
class HedgeCandidate:
    source_pillar: str
    hedge_pillar: str
    source_exposure: str
    hedge_instrument: str
    direction: str
    size: float
    estimated_cost: float
    expected_protection: float
    basis_risk: float
    correlation: float | None
    lead_lag_seconds: int | None
    drawdown_reduction: float | None
    volatility_reduction: float | None
    net_pnl_effect: float | None
    evidence_samples: int = 0
    state: str = "SHADOW_RESEARCH"


def hedge_state(samples: int, correlation: float | None, *, minimum_samples: int = 30) -> str:
    if samples < minimum_samples or correlation is None:
        return "COLLECTING_EVIDENCE"
    if correlation <= -0.2:
        return "SHADOW_CANDIDATE"
    return "RESEARCH_ONLY"


@dataclass
class CashLedger:
    base_capital: float
    deployed_capital: float = 0.0
    reserved_capital: float = 0.0
    unrealized_pnl: float = 0.0
    realized_gross_pnl: float = 0.0
    fees: float = 0.0
    liquid_cash: float = 0.0
    harvested_cash: float = 0.0
    redeployable_cash: float = 0.0

    @property
    def realized_net_pnl(self) -> float:
        return self.realized_gross_pnl - self.fees

    @property
    def equity(self) -> float:
        return self.base_capital + self.realized_net_pnl + self.unrealized_pnl

    def settle(self, *, gross_pnl: float, fees: float, released_capital: float, eligible_profit: bool = True) -> None:
        self.realized_gross_pnl += gross_pnl
        self.fees += max(fees, 0.0)
        self.deployed_capital = max(self.deployed_capital - max(released_capital, 0.0), 0.0)
        self.liquid_cash += released_capital + gross_pnl - max(fees, 0.0)
        if eligible_profit:
            self.harvested_cash += max(gross_pnl - max(fees, 0.0), 0.0)
            self.redeployable_cash += max(gross_pnl - max(fees, 0.0), 0.0)


@dataclass(frozen=True)
class CounterfactualDecision:
    decision_id: str
    chosen: Opportunity | None
    candidates: tuple[Opportunity, ...]
    rejected: tuple[Opportunity, ...]
    capital_constraint: str
    risk_constraint: str
    outcome: float | None = None
    alternative_outcomes: Mapping[str, float] = field(default_factory=dict)


def pillar_hierarchy() -> dict[str, tuple[str, ...]]:
    return {pillar: (("predictions", "perps") if pillar == "kalshi" else ()) for pillar in SIX_PILLARS}


def global_state(*, opportunities: Iterable[Opportunity], cash: CashLedger) -> dict[str, object]:
    ranked = rank_opportunities(opportunities, available_cash=cash.redeployable_cash + max(cash.liquid_cash, 0.0))
    best = ranked[0] if ranked else None
    return {"pillars": SIX_PILLARS, "best_opportunity": best.instrument if best else None,
            "best_pillar": best.pillar if best else None, "available_cash": cash.liquid_cash,
            "redeployable_cash": cash.redeployable_cash, "decision": "TRADE" if best else "HOLD_CASH"}
