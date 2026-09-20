#!/usr/bin/env python3
"""Build the shared Kalshi authorization snapshot from current evidence.

Provider capacity is deliberately kept separate from the internal $1,000
authorization. Unresolved provider exposure reserves the whole pool
conservatively; it is never assigned to strategy P&L.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from autotrader.capital_allocations import KALSHI_DEMO_BASE_CAPITAL


def main() -> dict[str, object]:
    root = Path(os.getenv("TRADING_PLATFORM_ROOT", "."))
    perps = json.loads((root / "var/kalshi/execution-perps.json").read_text())
    predictions = json.loads((root / "var/kalshi/execution-predictions.json").read_text())
    reconciliation = json.loads((root / "var/reports/kalshi-existing-position-reconciliation.json").read_text())
    perps_positions = reconciliation.get("perps_positions") or []
    perps_orders = int(perps.get("open_orders") or 0)
    predictions_orders = int(predictions.get("orders") or 0)
    unresolved = len(perps_positions) > 0
    # The provider rows have no usable quantity/margin/ownership basis. A
    # full-pool conservative reservation is therefore safer than inventing a
    # smaller notional or treating unreadable ownership as free capacity.
    committed = KALSHI_DEMO_BASE_CAPITAL if unresolved else 0.0
    pending = 0.0
    payload = {
        "schema_version": "kalshi-shared-capital-v1",
        "predictions_committed": 0.0,
        "perps_committed": committed,
        "working_orders_reserved": KALSHI_DEMO_BASE_CAPITAL if perps_orders or predictions_orders else 0.0,
        "pending_reservations": pending,
        "unresolved_fills_reserved": KALSHI_DEMO_BASE_CAPITAL if unresolved else 0.0,
        "total_committed": committed,
        "total_pending": pending,
        "internal_available": max(KALSHI_DEMO_BASE_CAPITAL - committed - pending, 0.0),
        "provider_equity": perps.get("account_equity", "UNKNOWN"),
        "provider_margin_used": perps.get("margin_used", "UNKNOWN"),
        "provider_available_capacity": perps.get("available_balance", "UNKNOWN"),
        "provider_positions": len(perps_positions),
        "provider_working_orders": perps_orders + predictions_orders,
        "ownership_state": "UNRESOLVED_PROVIDER_EXPOSURE" if unresolved else "NO_PROVIDER_EXPOSURE_OBSERVED",
        "state_confidence": "LOW" if unresolved else "MEDIUM",
        "source": "authenticated Kalshi DEMO reconciliation plus execution snapshots",
        "observed_at": datetime.now(UTC).isoformat(),
        "invariant": committed + pending <= KALSHI_DEMO_BASE_CAPITAL,
    }
    destination = root / "var/kalshi/execution-shared-capital.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".shared-capital.", dir=destination.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(name, destination)
    print(json.dumps(payload, sort_keys=True))
    return payload


if __name__ == "__main__":
    main()
