from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime

from .brokers.practice_orders import (
    _alpaca_credentials,
    _alpaca_headers,
    _request_json,
    submit_alpaca_paper_protected_order,
    submit_oanda_practice_market_order,
)
from .brokers.safety import alpaca_open_positions, oanda_open_positions
from .models import AssetClass, Position
from .portfolio_ledger import PortfolioLedger
from .preflight import run_preflight
from .reconciliation import normalize_alpaca_positions, normalize_oanda_positions


def _print_result(result) -> None:
    print(
        json.dumps(
            {"broker": result.broker, "ok": result.ok, "message": result.message, "details": result.details},
            indent=2,
            sort_keys=True,
        )
    )


def _sync_submitted_position(
    *,
    broker: str,
    symbol: str,
    stop_price: float,
    ledger_path: str,
    initial_equity: float,
    expected_quantity: float | None = None,
    asset_class: AssetClass | None = None,
    attempts: int = 10,
    delay_seconds: float = 0.25,
    quantity_tolerance: float = 0.005,
    broker_order_id: str | None = None,
) -> dict[str, object]:
    if quantity_tolerance < 0:
        raise ValueError("quantity_tolerance cannot be negative")
    normalized_symbol = symbol.strip().upper().replace("_", "/") if broker == "oanda" else symbol.strip().upper()
    broker_position = None
    order_snapshot = None
    order_status = None
    reconciliation_state = "reconciliation_pending"
    for _ in range(attempts):
        if broker == "alpaca" and broker_order_id:
            try:
                key, secret, base_url = _alpaca_credentials()
                order_snapshot, _ = _request_json(
                    f"{base_url}/v2/orders/{broker_order_id}",
                    method="GET",
                    headers=_alpaca_headers(key, secret),
                )
                if isinstance(order_snapshot, dict):
                    order_status = str(order_snapshot.get("status") or "").lower()
            except Exception:
                order_snapshot = None
                order_status = None
        if broker == "alpaca":
            records = alpaca_open_positions().details.get("positions", [])
            positions = normalize_alpaca_positions(records)
        else:
            records = oanda_open_positions().details.get("positions", [])
            positions = normalize_oanda_positions(records)
        broker_position = next((item for item in positions if item.symbol == normalized_symbol), None)
        if broker_position is not None and abs(broker_position.quantity) > 1e-12:
            if expected_quantity is None:
                reconciliation_state = "broker_confirmed"
                break
            difference = abs(abs(expected_quantity) - abs(broker_position.quantity))
            allowed = max(1e-8, abs(expected_quantity) * quantity_tolerance)
            if difference <= allowed:
                reconciliation_state = "exact_match" if difference <= 1e-8 else "fractional_reconciliation"
                break
            if abs(broker_position.quantity) + 1e-12 >= abs(expected_quantity):
                reconciliation_state = "broker_confirmed"
                break
            reconciliation_state = "material_mismatch"
            break
        if order_status in {"filled", "partially_filled"}:
            reconciliation_state = "filled_position_pending"
        elif order_status in {"new", "accepted", "pending_new", "held", "calculated"}:
            reconciliation_state = "order_pending"
        elif order_status in {"rejected", "canceled", "expired"}:
            reconciliation_state = "failed"
            break
        time.sleep(delay_seconds)

    if broker_position is None or abs(broker_position.quantity) <= 1e-12:
        if order_status in {"filled", "partially_filled"}:
            return {
                "symbol": normalized_symbol,
                "quantity": None,
                "requested_quantity": expected_quantity,
                "average_price": None,
                "stop_price": stop_price,
                "asset_class": (asset_class or (AssetClass.FOREX if broker == "oanda" else AssetClass.ETF)).value,
                "ledger_path": ledger_path,
                "reconciliation_status": "filled_position_pending",
                "reconciliation_difference": None,
                "order_status": order_status,
                "broker_order_id": broker_order_id,
            }
        if order_status in {"new", "accepted", "pending_new", "held", "calculated"}:
            return {
                "symbol": normalized_symbol,
                "quantity": None,
                "requested_quantity": expected_quantity,
                "average_price": None,
                "stop_price": stop_price,
                "asset_class": (asset_class or (AssetClass.FOREX if broker == "oanda" else AssetClass.ETF)).value,
                "ledger_path": ledger_path,
                "reconciliation_status": "order_pending",
                "reconciliation_difference": None,
                "order_status": order_status,
                "broker_order_id": broker_order_id,
            }
        raise RuntimeError(
            f"Order was submitted but {normalized_symbol} was not visible at the broker after bounded reconciliation; "
            "ledger was not changed and new exposure must remain blocked until reconciled."
        )
    reconciliation_status = (
        reconciliation_state if reconciliation_state != "reconciliation_pending" else "broker_confirmed"
    )
    reconciliation_difference = 0.0
    if expected_quantity is not None:
        reconciliation_difference = abs(abs(expected_quantity) - abs(broker_position.quantity))
        allowed = max(1e-8, abs(expected_quantity) * quantity_tolerance)
        if reconciliation_difference <= allowed:
            reconciliation_status = "exact_match" if reconciliation_difference <= 1e-8 else "fractional_reconciliation"
        elif abs(broker_position.quantity) + 1e-12 < abs(expected_quantity):
            reconciliation_status = (
                "filled_position_pending"
                if order_status in {"filled", "partially_filled"}
                else "material_mismatch"
            )
            if reconciliation_status == "material_mismatch":
                raise RuntimeError(
                    f"Order was submitted for {expected_quantity} {normalized_symbol}, but broker "
                    f"position only reached {broker_position.quantity} during sync; ledger was not changed."
                )
        else:
            reconciliation_status = "broker_confirmed"

    ledger = PortfolioLedger(ledger_path)
    loaded = ledger.load_portfolio()
    if loaded is None:
        from .models import PortfolioState
        portfolio = PortfolioState(equity=initial_equity, cash=initial_equity)
        peak = initial_equity
    else:
        portfolio, peak = loaded

    resolved_asset_class = asset_class or (AssetClass.FOREX if broker == "oanda" else AssetClass.ETF)
    average_price = broker_position.average_price
    if average_price is None or average_price <= 0:
        average_price = stop_price
    if reconciliation_status in {"exact_match", "fractional_reconciliation", "broker_confirmed"}:
        portfolio.positions[normalized_symbol] = Position(
            symbol=normalized_symbol,
            asset_class=resolved_asset_class,
            quantity=broker_position.quantity,
            average_price=average_price,
            stop_price=stop_price,
            initial_stop_price=stop_price,
            highest_price=average_price,
            opened_at=datetime.now(UTC),
        )
        ledger.save_portfolio(portfolio, peak_equity=peak)
    return {
        "symbol": normalized_symbol,
        "quantity": broker_position.quantity,
        "requested_quantity": expected_quantity,
        "average_price": average_price,
        "stop_price": stop_price,
        "asset_class": resolved_asset_class.value,
        "ledger_path": ledger_path,
        "reconciliation_status": reconciliation_status,
        "reconciliation_difference": reconciliation_difference,
        "order_status": order_status,
        "broker_order_id": broker_order_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit one explicitly confirmed broker-protected paper/practice test order"
    )
    parser.add_argument("--broker", required=True, choices=["alpaca", "oanda"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument("--qty", type=float)
    parser.add_argument("--units", type=int, default=1)
    parser.add_argument(
        "--stop-price",
        type=float,
        required=True,
        help="Required broker-side protective stop price for the practice test",
    )
    parser.add_argument(
        "--client-order-id",
        help="Optional idempotency/client order identifier generated by the safety layer",
    )
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--idempotency", default="var/autotrader/idempotency.db")
    parser.add_argument("--initial-equity", type=float, default=3000.0)
    parser.add_argument(
        "--confirm-practice-order",
        action="store_true",
        help="Required acknowledgement that this command submits a simulated broker order",
    )
    args = parser.parse_args()

    if not args.confirm_practice_order:
        parser.error("--confirm-practice-order is required")
    if args.stop_price <= 0:
        parser.error("--stop-price must be positive")

    preflight = run_preflight(
        ledger_path=args.ledger,
        idempotency_path=args.idempotency,
        initial_equity=args.initial_equity,
    )
    if not preflight.ready:
        parser.error("practice-order submission blocked by preflight: " + ", ".join(preflight.failed_checks))

    if args.broker == "alpaca":
        if args.qty is None or args.qty <= 0:
            parser.error("--qty must be positive for Alpaca protected orders")
        result = submit_alpaca_paper_protected_order(
            args.symbol,
            side=args.side,
            qty=args.qty,
            stop_price=args.stop_price,
            client_order_id=args.client_order_id,
        )
        expected_quantity = args.qty
    else:
        units = abs(args.units) if args.side == "buy" else -abs(args.units)
        result = submit_oanda_practice_market_order(
            args.symbol,
            units=units,
            stop_price=args.stop_price,
            client_order_id=args.client_order_id,
        )
        expected_quantity = abs(units)

    if result.ok:
        try:
            sync = _sync_submitted_position(
                broker=args.broker,
                symbol=args.symbol,
                stop_price=args.stop_price,
                ledger_path=args.ledger,
                initial_equity=args.initial_equity,
                expected_quantity=expected_quantity,
            )
            result.details["ledger_sync"] = sync
        except RuntimeError as exc:
            result.details["ledger_sync_error"] = str(exc)
    _print_result(result)


if __name__ == "__main__":
    main()
