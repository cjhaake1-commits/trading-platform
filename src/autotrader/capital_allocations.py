from __future__ import annotations

from math import isfinite

from .models import AssetClass

# Initial economic capital, not a provider balance or leveraged buying power.
CAPITAL_POLICY_ID = "income-6000-v1"
PILLAR_CAPITAL = 1000.0

PILLAR_EQUITIES = "alpaca_equities"
PILLAR_FOREX = "oanda_fx"
PILLAR_CRYPTO = "alpaca_crypto"
PILLAR_METALS = "alpaca_metals"
PILLAR_IBKR_GLOBAL = "ibkr_global"
# Preserve the existing international ledger key for compatibility.
PILLAR_INTERNATIONAL = PILLAR_IBKR_GLOBAL
PILLAR_KALSHI = "kalshi"

PILLAR_ALLOCATIONS = {
    PILLAR_EQUITIES: PILLAR_CAPITAL,
    PILLAR_FOREX: PILLAR_CAPITAL,
    PILLAR_CRYPTO: PILLAR_CAPITAL,
    PILLAR_METALS: PILLAR_CAPITAL,
    PILLAR_IBKR_GLOBAL: PILLAR_CAPITAL,
}
TOTAL_PAPER_CAPITAL = sum(PILLAR_ALLOCATIONS.values())
KALSHI_DEMO_BASE_CAPITAL = PILLAR_CAPITAL
SIX_PILLAR_BASE_CAPITAL = TOTAL_PAPER_CAPITAL + KALSHI_DEMO_BASE_CAPITAL
INTERNATIONAL_SIM_CAPITAL = PILLAR_ALLOCATIONS[PILLAR_INTERNATIONAL]
METALS_PAPER_CAPITAL = PILLAR_ALLOCATIONS[PILLAR_METALS]

ACTIVE_PILLARS = (PILLAR_EQUITIES, PILLAR_FOREX, PILLAR_CRYPTO, PILLAR_METALS)
RESERVED_PILLARS = (PILLAR_IBKR_GLOBAL,)
KALSHI_CHILD_PILLARS = ("kalshi_predictions", "kalshi_perps")
SIX_PILLARS = (
    PILLAR_EQUITIES,
    PILLAR_CRYPTO,
    PILLAR_FOREX,
    PILLAR_METALS,
    PILLAR_IBKR_GLOBAL,
    PILLAR_KALSHI,
)
KALSHI_CHILD_MAX = KALSHI_DEMO_BASE_CAPITAL / len(KALSHI_CHILD_PILLARS)


def kalshi_pool_available(*, committed: float, pending: float, realized_profit: float = 0.0) -> float:
    """Shared economic headroom; signed net P&L includes losses as well as gains.

    Provider availability, settlement, withdrawals, open losses, and risk gates
    must further constrain this amount. This helper never authorizes leverage.
    """
    values = (committed, pending, realized_profit)
    if not all(isfinite(value) for value in values) or committed < 0 or pending < 0:
        return 0.0
    return max(KALSHI_DEMO_BASE_CAPITAL + realized_profit - committed - pending, 0.0)


def validate_kalshi_reservation(*, predictions_committed: float, perps_committed: float,
                                predictions_pending: float = 0.0, perps_pending: float = 0.0,
                                realized_profit: float = 0.0) -> bool:
    values = (predictions_committed, perps_committed, predictions_pending, perps_pending)
    if not isfinite(realized_profit) or not all(isfinite(value) and value >= 0 for value in values):
        return False
    return sum(values) <= max(KALSHI_DEMO_BASE_CAPITAL + realized_profit, 0.0)


def pillar_for_asset(asset_class: AssetClass) -> str:
    if asset_class is AssetClass.FOREX:
        return PILLAR_FOREX
    if asset_class is AssetClass.CRYPTO:
        return PILLAR_CRYPTO
    return PILLAR_EQUITIES
