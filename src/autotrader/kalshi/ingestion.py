"""Opt-in, idempotent Kalshi research ingestion; never an execution service."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .client import KalshiReadOnlyClient
from .config import KalshiConfig
from .storage import KalshiResearchStore


def observation_id(family: str, endpoint: str, payload: dict[str, Any]) -> str:
    raw = json.dumps([family, endpoint, payload], sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def ingest_once(store: KalshiResearchStore, *, client: KalshiReadOnlyClient | None = None) -> int:
    """Collect one public market snapshot when KALSHI_RESEARCH_ENABLED=true."""
    config = (client.config if client else KalshiConfig.from_env())
    if not config.research_enabled:
        return 0
    transport = client or KalshiReadOnlyClient(config)
    retrieved = datetime.now(UTC).isoformat()
    payload = transport.markets(limit="100")
    records = payload.get("markets", []) if isinstance(payload, dict) else []
    for market in records:
        ticker = str(market.get("ticker") or market.get("market_ticker") or "")
        store.put_observation({
            "id": observation_id("predictions", "markets", market),
            "family": "predictions", "observation_type": "market", "payload": market,
            "retrieved_at": retrieved, "provider_generated_at": market.get("updated_time"),
            "endpoint": "markets", "instrument": ticker, "quality": "FRESH",
        })
    return len(records)
