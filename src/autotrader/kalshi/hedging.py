from __future__ import annotations

from dataclasses import dataclass

from .models import KalshiMarket


@dataclass(frozen=True)
class ShadowHedgeObservation:
    candidate: str
    hypothetical_cost: float | None
    hypothetical_payout: float | None
    estimated_drawdown_reduction: float | None
    hedge_efficiency: float | None
    basis_mismatch_risk: float | None
    effective: bool = False
    mode: str = "shadow"


def evaluate_shadow_hedge(market: KalshiMarket, exposure: float, *, contracts: int = 1) -> ShadowHedgeObservation:
    cost = market.yes_ask * contracts if market.yes_ask is not None else None
    payout = float(contracts) if cost is not None else None
    reduction = min(abs(exposure), payout) if payout is not None else None
    efficiency = reduction / cost if reduction is not None and cost else None
    return ShadowHedgeObservation(market.market_ticker, cost, payout, reduction, efficiency, None)
