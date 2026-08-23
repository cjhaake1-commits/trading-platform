from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import KalshiMarket


def probability_features(market: KalshiMarket, *, previous: dict[str, float] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Return research-only, deterministic features; missing inputs stay None."""
    bid, ask = market.yes_bid, market.yes_ask
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread = ask - bid if bid is not None and ask is not None else None
    previous = previous or {}
    change = mid - previous["mid_probability"] if mid is not None and "mid_probability" in previous else None
    current = now or datetime.now(UTC)
    resolution = None
    if market.close_time:
        resolution = max(0.0, (market.close_time - current).total_seconds() / 3600)
    return {
        "kalshi.implied_probability": mid,
        "kalshi.probability_change": change,
        "kalshi.1h_change": previous.get("1h_change"),
        "kalshi.6h_change": previous.get("6h_change"),
        "kalshi.24h_change": previous.get("24h_change"),
        "kalshi.velocity": previous.get("velocity"),
        "kalshi.acceleration": previous.get("acceleration"),
        "kalshi.spread": spread,
        "kalshi.volume": market.volume,
        "kalshi.liquidity": market.liquidity,
        "kalshi.time_to_resolution_hours": resolution,
        "kalshi.category": market.category,
        "source": "kalshi",
        "broker_control": False,
        "execution_enabled": False,
    }
