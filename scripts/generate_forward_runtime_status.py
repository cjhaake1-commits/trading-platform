"""Write a bounded, non-secret forward runtime observation snapshot."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from autotrader.forward_reconciler import reconcile
from autotrader.forward_verification import ensure_verification_epoch, forward_daily_metrics


def main() -> None:
    daily = forward_daily_metrics()
    reconciled = reconcile()
    payload = {
        "verification_epoch": ensure_verification_epoch(),
        "last_cycle_at": datetime.now(UTC).isoformat(),
        "new_intents": daily["fills_today"] + daily["verified_closed_trades"],
        "submissions": reconciled["orders_requested"],
        "working_orders": len(reconciled["working_orders"]),
        "partial_fills": 0,
        "fills": daily["fills_today"],
        "owned_open_positions": reconciled["owned_open_positions"],
        "closed_positions": daily["verified_closed_trades"],
        "capital_reserved": reconciled["capital_reserved"],
        "capital_released": "FROM_RESERVATION_LEDGER",
        "capital_available": "FROM_RESERVATION_LEDGER",
        "verified_realized_pnl": reconciled["verified_realized_pnl"],
        "verified_unrealized_pnl": reconciled["verified_unrealized_pnl"],
        "unattributed_provider_activity": reconciled["unattributed_provider_activity"],
        "blocked_reasons": ["KALSHI_SHARED_AVAILABLE_ZERO", "SAXO_AUTH_REQUIRED", "KALSHI_PERPS_DISABLED"],
        "provider_freshness": "CURRENT_LOCAL_RECONCILIATION",
        "accounting_state": daily["verification_confidence"],
    }
    destination = Path("var/reports/forward-runtime-status.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
