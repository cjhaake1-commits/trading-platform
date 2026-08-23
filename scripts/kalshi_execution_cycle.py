#!/usr/bin/env python3
"""Execution-engine heartbeat with an immutable no-trade safety gate."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from autotrader.kalshi.client import KalshiReadOnlyClient
from autotrader.kalshi.config import KalshiConfig


def cycle() -> dict[str, object]:
    engine = os.getenv("KALSHI_ENGINE", "predictions").lower()
    config = KalshiConfig.from_env()
    result: dict[str, object] = {"engine": engine, "observed_at": datetime.now(UTC).isoformat(),
                                 "orders": 0, "fills": 0, "decision": "HOLD_CASH",
                                 "execution_enabled": config.demo_trading_enabled, "broker_control": False}
    if (config.environment != "demo" or config.trading_enabled or not config.demo_trading_enabled
            or config.paper_capital <= 0):
        result["decision"] = "FAIL_CLOSED"
        return result
    client = KalshiReadOnlyClient(config)
    try:
        if engine == "predictions":
            markets = client.markets(limit="100")
            result.update({"state": "SCANNING", "markets": len(markets.get("markets", []))})
        elif engine == "reconciliation":
            result.update({"state": "CONNECTED", "positions": len(client.positions(limit="100").get("market_positions", [])),
                           "orders": len(client.orders_read_only(limit="100").get("orders", [])),
                           "fills": len(client.fills(limit="100").get("fills", []))})
        else:
            enabled = client.perps_enabled()
            markets = client.perps_markets(limit="100")
            result.update({"state": "SCANNING" if enabled.get("enabled", True) else "EXTERNAL_BLOCK",
                           "margin_enabled": enabled, "instruments": len(markets.get("markets", []))})
    except Exception as exc:
        result.update({"state": "API_DEGRADED", "error": type(exc).__name__})
    return result


if __name__ == "__main__":
    print(json.dumps(cycle(), sort_keys=True))
