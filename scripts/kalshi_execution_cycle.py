#!/usr/bin/env python3
"""Execution-engine heartbeat with an immutable no-trade safety gate."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from autotrader.kalshi.client import KalshiReadOnlyClient
from autotrader.kalshi.config import KalshiConfig


def _write_status(engine: str, result: dict[str, object]) -> None:
    path = Path(os.getenv("KALSHI_EXECUTION_STATUS_DIR", "var/kalshi")) / f"execution-{engine}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")


def _prediction_funnel(markets: list[dict[str, object]]) -> dict[str, int]:
    data_valid = [m for m in markets if m.get("yes_bid_dollars") is not None and m.get("yes_ask_dollars") is not None]
    liquid = [m for m in data_valid if float(m.get("yes_bid_size_fp") or 0) > 0 and float(m.get("yes_ask_size_fp") or 0) > 0]
    spread_valid = [m for m in liquid if float(m.get("yes_ask_dollars") or 1) - float(m.get("yes_bid_dollars") or 0) <= 0.10]
    return {"scanned": len(markets), "data_valid": len(data_valid), "liquid": len(liquid),
            "spread_valid": len(spread_valid), "fee_valid": 0, "positive_edge": 0,
            "risk_approved": 0, "capital_approved": 0, "orders_submitted": 0}


def _perps_funnel(markets: list[dict[str, object]]) -> dict[str, int]:
    active = [m for m in markets if str(m.get("status") or "active").lower() in {"active", "open"}]
    return {"scanned": len(markets), "data_valid": len(active), "liquid": 0, "spread_valid": 0,
            "band_valid": 0, "fee_valid": 0, "positive_edge": 0, "risk_approved": 0,
            "capital_approved": 0, "orders_submitted": 0}


def cycle() -> dict[str, object]:
    engine = os.getenv("KALSHI_ENGINE", "predictions").lower()
    config = KalshiConfig.from_env()
    result: dict[str, object] = {"engine": engine, "observed_at": datetime.now(UTC).isoformat(),
                                 "orders": 0, "fills": 0, "decision": "HOLD_CASH",
                                 "execution_enabled": config.demo_trading_enabled, "broker_control": False}
    if (config.environment != "demo" or config.trading_enabled or not config.demo_trading_enabled
            or config.paper_capital <= 0):
        result["decision"] = "FAIL_CLOSED"
        result["last_rejection_reason"] = "SAFETY_GATE"
        _write_status(engine, result)
        return result
    client = KalshiReadOnlyClient(config)
    try:
        if engine == "predictions":
            markets = client.markets(limit="100")
            rows = markets.get("markets", [])
            funnel = _prediction_funnel(rows)
            result.update({"state": "SCANNING", "markets": len(rows), "funnel": funnel,
                           "last_rejection_reason": "NO_POSITIVE_EDGE" if funnel["spread_valid"] else "INSUFFICIENT_SPREAD_OR_LIQUIDITY"})
        elif engine == "reconciliation":
            result.update({"state": "CONNECTED", "positions": len(client.positions(limit="100").get("market_positions", [])),
                           "orders": len(client.orders_read_only(limit="100").get("orders", [])),
                           "fills": len(client.fills(limit="100").get("fills", []))})
        else:
            enabled = client.perps_enabled()
            markets = client.perps_markets(limit="100")
            rows = markets.get("markets", [])
            funnel = _perps_funnel(rows)
            result.update({"state": "SCANNING" if enabled.get("enabled", True) else "EXTERNAL_BLOCK",
                           "margin_enabled": enabled, "instruments": len(rows), "funnel": funnel,
                           "funding_state": "OPTIONAL_UNAVAILABLE", "fee_state": "OPTIONAL_UNAVAILABLE",
                           "last_rejection_reason": "NO_POSITIVE_EDGE" if enabled.get("enabled", True) else "MARGIN_DISABLED"})
    except Exception as exc:
        result.update({"state": "API_DEGRADED", "error": type(exc).__name__})
        result["last_rejection_reason"] = "API_DEGRADED"
    _write_status(engine, result)
    return result


if __name__ == "__main__":
    print(json.dumps(cycle(), sort_keys=True))
