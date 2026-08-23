"""Shared, read-only Kalshi research primitives.

This module intentionally contains no execution path.  It is usable without
credentials and keeps provider data/provenance explicit for later research.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping


class DataQuality(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class NormalizedTimestamp:
    raw: Any
    raw_type: str
    utc: datetime
    provider_family: str


def normalize_timestamp(value: Any, *, provider_family: str) -> NormalizedTimestamp:
    """Normalize validated seconds, milliseconds, or RFC3339 to UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not accepted")
        return NormalizedTimestamp(value, "datetime", value.astimezone(UTC), provider_family)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = Decimal(str(value))
        # Epoch unit is explicit or validated by magnitude, never by field name.
        if number.copy_abs() >= Decimal("1e11"):
            seconds = number / Decimal(1000)
            kind = "epoch_milliseconds"
        elif number.copy_abs() < Decimal("1e11"):
            seconds = number
            kind = "epoch_seconds"
        else:
            raise ValueError("unsupported epoch timestamp")
        return NormalizedTimestamp(value, kind, datetime.fromtimestamp(float(seconds), UTC), provider_family)
    if isinstance(value, str):
        text = value.strip()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("RFC3339 timestamp requires timezone")
        return NormalizedTimestamp(value, "rfc3339", parsed.astimezone(UTC), provider_family)
    raise ValueError(f"unsupported timestamp type: {type(value).__name__}")


def price(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid price: {value!r}") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise ValueError("Kalshi price must be between 0 and 1")
    return result


@dataclass(frozen=True)
class VariableTick:
    increment: Decimal
    def __post_init__(self) -> None:
        if self.increment <= 0:
            raise ValueError("tick must be positive")
    def valid(self, value: Decimal) -> bool:
        return (value / self.increment) == (value / self.increment).to_integral_value()


@dataclass(frozen=True)
class PriceBand:
    reference: Decimal
    lower: Decimal
    upper: Decimal
    timestamp: NormalizedTimestamp
    def admissible(self, side: str, value: Decimal) -> bool:
        side = side.lower()
        return self.lower <= value if side == "bid" else self.upper >= value if side == "ask" else False


@dataclass(frozen=True)
class Freshness:
    source_timestamp: NormalizedTimestamp | None
    retrieved_at: datetime
    quality: DataQuality
    estimated_lag_seconds: float | None

    @classmethod
    def from_source(cls, source: Any, retrieved_at: datetime, *, provider_family: str, max_age_seconds: float = 60) -> "Freshness":
        retrieved_at = retrieved_at.astimezone(UTC)
        if source is None:
            return cls(None, retrieved_at, DataQuality.UNAVAILABLE, None)
        normalized = normalize_timestamp(source, provider_family=provider_family)
        lag = max(0.0, (retrieved_at - normalized.utc).total_seconds())
        return cls(normalized, retrieved_at, DataQuality.FRESH if lag <= max_age_seconds else DataQuality.STALE, lag)


@dataclass(frozen=True)
class Provenance:
    provider: str = "kalshi"
    family: str = "predictions"
    endpoint: str | None = None
    exchange_index: str | None = None
    instrument: str | None = None
    provider_generated_at: NormalizedTimestamp | None = None
    received_at: datetime | None = None
    normalization_version: str = "kalshi-foundation-v2"
    broker_control: bool = False
    execution_enabled: bool = False


@dataclass(frozen=True)
class ExpectedEdge:
    model_probability: Decimal
    market_probability: Decimal
    spread_cost: Decimal
    expected_fee_cost: Decimal
    execution_uncertainty: Decimal
    model_uncertainty: Decimal
    @property
    def estimated_actionable_edge(self) -> Decimal:
        return self.model_probability - self.market_probability - self.spread_cost - self.expected_fee_cost - self.execution_uncertainty - self.model_uncertainty


@dataclass(frozen=True)
class ResearchObservation:
    timestamp: datetime
    payload: Mapping[str, Any]
    provenance: Provenance
    quality: DataQuality = DataQuality.FRESH
