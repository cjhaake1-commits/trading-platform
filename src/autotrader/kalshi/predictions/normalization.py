from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..foundation import price
from .models import PredictionMarket


def normalize_market(raw: dict[str, Any]) -> PredictionMarket:
    def d(name: str) -> Decimal | None:
        return price(raw.get(name)) if raw.get(name) is not None else None
    return PredictionMarket(
        event_id=raw.get("event_id"), market_ticker=raw["ticker"], series=raw.get("series_ticker") or raw.get("series"),
        category=raw.get("category"), title=raw.get("title"), subtitle=raw.get("subtitle"), rules=raw.get("rules"),
        yes_bid=d("yes_bid"), yes_ask=d("yes_ask"), no_bid=d("no_bid"), no_ask=d("no_ask"), tick_size=d("tick_size"),
        volume=d("volume"), open_interest=d("open_interest"), liquidity=d("liquidity"), status=raw.get("status"), result=raw.get("result"),
        exchange_index=raw.get("exchange_index"),
    )

