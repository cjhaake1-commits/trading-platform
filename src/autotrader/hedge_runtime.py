"""Evidence-gated hedge candidate generation."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class HedgeCandidate:
    target_exposure: str
    hedge_instrument: str
    hedge_direction: str
    hedge_ratio: float
    capital_required: float
    expected_cost: float
    expected_downside_reduction: float
    expected_return_impact: float
    expected_drawdown_impact: float
    basis_risk: float
    qualified: bool

    def as_dict(self): return asdict(self)


def evaluate_hedge(*, target_exposure: str, hedge_instrument: str, hedge_direction: str,
                   hedge_ratio: float, capital_required: float, expected_cost: float,
                   expected_downside_reduction: float, expected_return_impact: float,
                   expected_drawdown_impact: float, basis_risk: float) -> HedgeCandidate:
    qualified = (hedge_ratio > 0 and capital_required > 0 and expected_cost >= 0
                 and expected_downside_reduction > expected_cost
                 and expected_drawdown_impact < 0 and 0 <= basis_risk <= 1)
    return HedgeCandidate(target_exposure, hedge_instrument, hedge_direction, hedge_ratio, capital_required, expected_cost, expected_downside_reduction, expected_return_impact, expected_drawdown_impact, basis_risk, qualified)
