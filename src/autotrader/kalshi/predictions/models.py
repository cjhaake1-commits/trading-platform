from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..foundation import Provenance


@dataclass(frozen=True)
class PredictionMarket:
    event_id: str | None
    market_ticker: str
    series: str | None = None
    category: str | None = None
    title: str | None = None
    subtitle: str | None = None
    rules: str | None = None
    yes_bid: Decimal | None = None
    yes_ask: Decimal | None = None
    no_bid: Decimal | None = None
    no_ask: Decimal | None = None
    tick_size: Decimal | None = None
    volume: Decimal | None = None
    open_interest: Decimal | None = None
    liquidity: Decimal | None = None
    close_time: datetime | None = None
    settlement_time: datetime | None = None
    status: str | None = None
    result: str | None = None
    exchange_index: str | None = None
    retrieved_at: datetime | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class OrderBook:
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    retrieved_at: datetime
    exchange_index: str | None = None
