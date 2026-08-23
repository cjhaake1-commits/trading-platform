from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PerpsInstrument:
    symbol: str
    exchange_index: str | None = None
    tick_size: Decimal | None = None
    status: str | None = None


@dataclass(frozen=True)
class FundingObservation:
    instrument: str
    rate: Decimal
    funding_at: datetime
    interval_seconds: int | None = None
    source: str = "kalshi"
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class MarginState:
    available_balance: Decimal | None = None
    margin_used: Decimal | None = None
    margin_available: Decimal | None = None
    position_exposure: Decimal | None = None
    maintenance_requirement: Decimal | None = None
    risk_state: str | None = None


@dataclass(frozen=True)
class PerpsPosition:
    instrument: str
    quantity: Decimal
    mark_price: Decimal | None = None
    reference_price: Decimal | None = None
    exchange_index: str | None = None


class TransfersDisabledError(RuntimeError):
    pass


def transfer(*args: object, **kwargs: object) -> None:
    raise TransfersDisabledError("Kalshi transfers are disabled in research-only foundation")

