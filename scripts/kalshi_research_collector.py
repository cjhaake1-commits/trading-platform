#!/usr/bin/env python3
"""Bounded read-only Kalshi Demo research collector."""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from autotrader.kalshi.client import KalshiReadOnlyClient
from autotrader.kalshi.ingestion import observation_id
from autotrader.kalshi.storage import KalshiResearchStore
from autotrader.research_platform import ResearchStore


def collect() -> dict[str, object]:
    cfg = __import__("autotrader.kalshi.config", fromlist=["KalshiConfig"]).KalshiConfig.from_env()
    if not cfg.research_enabled or cfg.environment != "demo" or cfg.trading_enabled or cfg.paper_capital != 0:
        raise RuntimeError("Kalshi collector safety gate failed")
    client = KalshiReadOnlyClient(cfg)
    db = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    store = KalshiResearchStore(db)
    learning = ResearchStore(os.getenv("KALSHI_LEARNING_DB", "var/research.db"))
    now = datetime.now(UTC).isoformat()
    result: dict[str, object] = {"retrieved_at": now, "predictions": 0, "perps": "NOT_DOCUMENTED", "errors": []}
    try:
        events = client.events(limit="100")
        markets = client.markets(limit="100")
        for endpoint, body, key in (("events", events, "events"), ("markets", markets, "markets")):
            for item in body.get(key, []) if isinstance(body, dict) else []:
                ticker = item.get("ticker") or item.get("event_ticker")
                record = {"family":"predictions", "observation_type":key[:-1], "payload":item,
                          "retrieved_at":now, "provider_generated_at":item.get("updated_time"),
                          "endpoint":endpoint, "instrument":ticker, "quality":"FRESH"}
                store.put_observation({"id":observation_id("predictions", endpoint, item), **record})
                if key == "markets":
                    bid = item.get("yes_bid_dollars")
                    ask = item.get("yes_ask_dollars")
                    features = {}
                    if bid is not None and ask is not None:
                        mid = (float(bid) + float(ask)) / 2
                        features["kalshi.implied_probability"] = mid
                        features["kalshi.spread"] = float(ask) - float(bid)
                    if item.get("volume_fp") is not None:
                        features["kalshi.volume"] = float(item["volume_fp"])
                    for name, value in features.items():
                        learning.put_feature(name=name, value=value, source="kalshi", experiment_id="kalshi_research",
                                             symbol=str(ticker or "unknown"), pillar="research", freshness="FRESH")
                    result["predictions"] = int(result["predictions"]) + 1
        for endpoint, getter in (("exchange/status", client.exchange_status), ("exchange/schedule", client.exchange_schedule),
                                 ("series/fee_changes", lambda: client.fee_changes(show_historical="false"))):
            body = getter()
            store.put_observation({"id":observation_id("predictions", endpoint, body), "family":"predictions",
                "observation_type":"exchange", "payload":body, "retrieved_at":now, "endpoint":endpoint, "quality":"FRESH"})
        for endpoint, getter in (("portfolio/balance", client.balance), ("portfolio/positions", lambda: client.positions(limit="100")),
                                 ("portfolio/orders", lambda: client.orders_read_only(limit="100")),
                                 ("portfolio/fills", lambda: client.fills(limit="100")),
                                 ("exchange/user_data_timestamp", client.user_data_timestamp)):
            try:
                body = getter()
                store.put_observation({"id":observation_id("predictions", endpoint, body), "family":"predictions",
                    "observation_type":"authenticated", "payload":body, "retrieved_at":now, "endpoint":endpoint, "quality":"FRESH"})
            except Exception as exc:
                result["errors"].append(f"{endpoint}:{type(exc).__name__}")
    except Exception as exc:
        result["errors"].append(type(exc).__name__)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    print(json.dumps(collect(), sort_keys=True))
