from decimal import Decimal
from typing import Any

from ..foundation import price
from .models import FundingObservation, PerpsInstrument


def normalize_instrument(raw: dict[str, Any]) -> PerpsInstrument:
    tick = price(raw["tick_size"]) if raw.get("tick_size") is not None else None
    return PerpsInstrument(raw["symbol"], raw.get("exchange_index"), tick, raw.get("status"))


def normalize_funding(raw: dict[str, Any], *, funding_at, retrieved_at=None) -> FundingObservation:
    return FundingObservation(raw["instrument"], Decimal(str(raw["rate"])), funding_at, raw.get("interval_seconds"), raw.get("source", "kalshi"), retrieved_at)

