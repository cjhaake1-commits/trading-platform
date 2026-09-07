#!/usr/bin/env python3
"""Create a secret-free, read-only Kalshi Demo state backup."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
from autotrader.kalshi.client import KalshiReadOnlyClient

def main() -> int:
    client = KalshiReadOnlyClient()
    calls = {
        "predictions_balance": client.balance,
        "predictions_positions": lambda: client.positions(limit="100"),
        "predictions_orders": lambda: client.orders_read_only(limit="100"),
        "predictions_fills": lambda: client.fills(limit="100"),
        "perps_balance": client.perps_balance,
        "perps_risk": client.perps_risk,
        "perps_positions": lambda: client.perps_positions(limit="100"),
        "perps_orders": lambda: client.perps("orders", limit="100"),
        "perps_fills": lambda: client.perps_fills(limit="100"),
        "perps_funding": client.perps_funding_rate,
        "perps_fees": client.perps_fee_tiers,
    }
    state = {"backup_created_at_utc": datetime.now(UTC).isoformat(), "environment": "demo", "read_only": True}
    for name, call in calls.items():
        try: state[name] = call()
        except Exception as exc: state[name] = {"error": type(exc).__name__}
    destination = Path("var/kalshi/backups") / f"demo-state-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(destination)
    return 0

if __name__ == "__main__": raise SystemExit(main())
