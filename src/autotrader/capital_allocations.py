from __future__ import annotations

from .models import AssetClass

TOTAL_PAPER_CAPITAL = 3000.0
PILLAR_CAPITAL = 1000.0

PILLAR_EQUITIES = "alpaca_equities"
PILLAR_FOREX = "oanda_fx"
PILLAR_CRYPTO = "alpaca_crypto"

PILLAR_ALLOCATIONS = {
    PILLAR_EQUITIES: PILLAR_CAPITAL,
    PILLAR_FOREX: PILLAR_CAPITAL,
    PILLAR_CRYPTO: PILLAR_CAPITAL,
}


def pillar_for_asset(asset_class: AssetClass) -> str:
    if asset_class is AssetClass.FOREX:
        return PILLAR_FOREX
    if asset_class is AssetClass.CRYPTO:
        return PILLAR_CRYPTO
    return PILLAR_EQUITIES
