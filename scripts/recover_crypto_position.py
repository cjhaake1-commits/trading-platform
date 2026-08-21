from __future__ import annotations

import argparse
import json

from autotrader.brokers.practice_orders import submit_alpaca_paper_crypto_stop_limit
from autotrader.brokers.safety import alpaca_open_positions, close_alpaca_position
from autotrader.models import AssetClass
from autotrader.order_test_app import _sync_submitted_position
from autotrader.preflight import run_preflight
from autotrader.reconciliation import normalize_alpaca_positions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Protect and reconcile one existing Alpaca paper crypto position."
    )
    parser.add_argument("symbol", help="Canonical symbol, e.g. BTC/USD")
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=0.02,
        help="Stop distance below broker average entry (default: 0.02)",
    )
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--idempotency", default="var/autotrader/idempotency.db")
    parser.add_argument("--initial-equity", type=float, default=3000.0)
    args = parser.parse_args()

    symbol = args.symbol.strip().upper().replace("_", "/")
    if not 0 < args.stop_pct < 0.25:
        raise SystemExit("ABORT: --stop-pct must be between 0 and 0.25")

    raw = alpaca_open_positions().details.get("positions", [])
    positions = normalize_alpaca_positions(raw)
    position = next((p for p in positions if p.symbol == symbol), None)
    if position is None or abs(position.quantity) <= 1e-12:
        raise SystemExit(f"ABORT: no open Alpaca paper position found for {symbol}")
    if position.quantity < 0:
        raise SystemExit("ABORT: recovery utility only supports long crypto positions")
    if position.average_price is None or position.average_price <= 0:
        raise SystemExit("ABORT: broker average entry price unavailable")

    stop_price = round(position.average_price * (1.0 - args.stop_pct), 2)
    print(
        json.dumps(
            {
                "symbol": symbol,
                "quantity": position.quantity,
                "average_price": position.average_price,
                "stop_price": stop_price,
            },
            indent=2,
        )
    )

    protection = submit_alpaca_paper_crypto_stop_limit(
        symbol,
        qty=abs(position.quantity),
        stop_price=stop_price,
        client_order_id=f"recovery-{symbol.replace('/', '')}-stop"[:48],
    )
    if not protection.ok:
        print(
            json.dumps(
                {
                    "protective_stop_ok": False,
                    "message": protection.message,
                    "details": protection.details,
                },
                indent=2,
                default=str,
            )
        )
        emergency = close_alpaca_position(symbol, ledger_path=args.ledger)
        print(
            json.dumps(
                {
                    "emergency_close_ok": emergency.ok,
                    "message": emergency.message,
                    "details": emergency.details,
                },
                indent=2,
                default=str,
            )
        )
        if not emergency.ok:
            raise SystemExit(
                "CRITICAL: protective stop failed and broker position still appears open; "
                "keep autonomous runtime stopped"
            )
        raise SystemExit("Protection failed; emergency close verified. Keep runtime stopped and inspect broker state.")

    sync = _sync_submitted_position(
        broker="alpaca",
        symbol=symbol,
        stop_price=stop_price,
        ledger_path=args.ledger,
        initial_equity=args.initial_equity,
        expected_quantity=abs(position.quantity),
        asset_class=AssetClass.CRYPTO,
        attempts=12,
        delay_seconds=0.25,
    )
    print(
        json.dumps(
            {
                "protective_stop_ok": True,
                "protective_order_id": protection.details.get("id"),
                "ledger_sync": sync,
            },
            indent=2,
            default=str,
        )
    )

    preflight = run_preflight(
        ledger_path=args.ledger,
        idempotency_path=args.idempotency,
        initial_equity=args.initial_equity,
    )
    print(
        json.dumps(
            {
                "preflight_ready": preflight.ready,
                "failed_checks": list(preflight.failed_checks),
                "messages": list(preflight.messages),
                "reconciliation_reason": preflight.reconciliation_reason,
            },
            indent=2,
            default=str,
        )
    )
    if not preflight.ready:
        raise SystemExit("Recovery completed but preflight is not ready; keep autonomous runtime stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
