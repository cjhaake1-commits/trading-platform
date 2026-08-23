from __future__ import annotations

from .models import AssetClass

TOTAL_PAPER_CAPITAL = 5000.0
KALSHI_DEMO_BASE_CAPITAL = 1000.0
SIX_PILLAR_BASE_CAPITAL = TOTAL_PAPER_CAPITAL + KALSHI_DEMO_BASE_CAPITAL
PILLAR_CAPITAL = 1000.0

PILLAR_EQUITIES = "alpaca_equities"
PILLAR_FOREX = "oanda_fx"
PILLAR_CRYPTO = "alpaca_crypto"
PILLAR_METALS = "alpaca_metals"
PILLAR_IBKR_GLOBAL = "ibkr_global"
# The existing fourth-pillar key is retained for ledger/backward compatibility.
# Saxo SIM is the read-only connectivity adapter for this international pillar.
PILLAR_INTERNATIONAL = PILLAR_IBKR_GLOBAL
INTERNATIONAL_SIM_CAPITAL = PILLAR_CAPITAL
METALS_PAPER_CAPITAL = PILLAR_CAPITAL

PILLAR_ALLOCATIONS = {
    PILLAR_EQUITIES: PILLAR_CAPITAL,
    PILLAR_FOREX: PILLAR_CAPITAL,
    PILLAR_CRYPTO: PILLAR_CAPITAL,
    PILLAR_METALS: PILLAR_CAPITAL,
    PILLAR_IBKR_GLOBAL: PILLAR_CAPITAL,
}

ACTIVE_PILLARS = (PILLAR_EQUITIES, PILLAR_FOREX, PILLAR_CRYPTO, PILLAR_METALS)
RESERVED_PILLARS = (PILLAR_IBKR_GLOBAL,)

PILLAR_KALSHI = "kalshi"
KALSHI_CHILD_PILLARS = ("kalshi_predictions", "kalshi_perps")
SIX_PILLARS = (
    PILLAR_EQUITIES,
    PILLAR_CRYPTO,
    PILLAR_FOREX,
    PILLAR_METALS,
    PILLAR_IBKR_GLOBAL,
    PILLAR_KALSHI,
)
KALSHI_CHILD_MAX = 700.0


def kalshi_pool_available(*, committed: float, pending: float, realized_profit: float = 0.0) -> float:
    """Return shared Kalshi capacity; child reservations cannot double count it."""
    return max(KALSHI_DEMO_BASE_CAPITAL + max(realized_profit, 0.0) - committed - pending, 0.0)


def validate_kalshi_reservation(*, predictions_committed: float, perps_committed: float,
                                predictions_pending: float = 0.0, perps_pending: float = 0.0,
                                realized_profit: float = 0.0) -> bool:
    values = (predictions_committed, perps_committed, predictions_pending, perps_pending)
    return all(value >= 0 for value in values) and sum(values) <= KALSHI_DEMO_BASE_CAPITAL + max(realized_profit, 0.0)


def pillar_for_asset(asset_class: AssetClass) -> str:
    if asset_class is AssetClass.FOREX:
        return PILLAR_FOREX
    if asset_class is AssetClass.CRYPTO:
        return PILLAR_CRYPTO
    return PILLAR_EQUITIES
