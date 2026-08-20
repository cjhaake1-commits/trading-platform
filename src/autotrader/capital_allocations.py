from __future__ import annotations

from .models import AssetClass

TOTAL_PAPER_CAPITAL = 5000.0
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


def pillar_for_asset(asset_class: AssetClass) -> str:
    if asset_class is AssetClass.FOREX:
        return PILLAR_FOREX
    if asset_class is AssetClass.CRYPTO:
        return PILLAR_CRYPTO
    return PILLAR_EQUITIES
