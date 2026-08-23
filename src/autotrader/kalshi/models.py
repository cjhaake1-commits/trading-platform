from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class KalshiEvent:
    event_id: str
    series: str | None = None
    category: str | None = None
    title: str | None = None
    subtitle: str | None = None
    rules: str | None = None
    close_time: datetime | None = None
    settlement_time: datetime | None = None
    status: str | None = None
    result: str | None = None
    retrieved_at: datetime | None = None
    source: str = "kalshi"
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class KalshiMarket:
    market_ticker: str
    event_id: str | None = None
    series: str | None = None
    category: str | None = None
    title: str | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    liquidity: float | None = None
    close_time: datetime | None = None
    settlement_time: datetime | None = None
    status: str | None = None
    result: str | None = None
    retrieved_at: datetime | None = None
    source: str = "kalshi"
    provenance: dict[str, Any] | None = None

