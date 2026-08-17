from __future__ import annotations

from .models import AssetClass

TOTAL_PAPER_CAPITAL = 4000.0
PILLAR_CAPITAL = 1000.0

PILLAR_EQUITIES = "alpaca_equities"
PILLAR_FOREX = "oanda_fx"
PILLAR_CRYPTO = "alpaca_crypto"
PILLAR_IBKR_GLOBAL = "ibkr_global"

PILLAR_ALLOCATIONS = {
    PILLAR_EQUITIES: PILLAR_CAPITAL,
    PILLAR_FOREX: PILLAR_CAPITAL,
    PILLAR_CRYPTO: PILLAR_CAPITAL,
    PILLAR_IBKR_GLOBAL: PILLAR_CAPITAL,
}

ACTIVE_PILLARS = (PILLAR_EQUITIES, PILLAR_FOREX, PILLAR_CRYPTO)
RESERVED_PILLARS = (PILLAR_IBKR_GLOBAL,)


def pillar_for_asset(asset_class: AssetClass) -> str:
    if asset_class is AssetClass.FOREX:
        return PILLAR_FOREX
    if asset_class is AssetClass.CRYPTO:
        return PILLAR_CRYPTO
    return PILLAR_EQUITIES
