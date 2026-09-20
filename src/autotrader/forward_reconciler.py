"""Independent manifest-first forward reconciliation; provider evidence wins."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping


def reconcile(*, manifest_path: str | Path = "var/autotrader/execution-manifest.jsonl",
              provider_orders: Iterable[Mapping[str, object]] = (),
              provider_fills: Iterable[Mapping[str, object]] = (),
              provider_positions: Iterable[Mapping[str, object]] = ()) -> dict[str, object]:
    events = []
    path = Path(manifest_path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    events.append(row)
            except ValueError:
                continue
    def number(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    orders = list(provider_orders)
    fills = list(provider_fills)
    positions = list(provider_positions)
    order_ids = {str(row.get("id") or row.get("order_id") or row.get("provider_order_id")) for row in orders}
    seen_fills = set()
    owned = []
    unattributed_fills = []
    linked_symbols = set()
    for row in fills:
        order_id = str(row.get("order_id") or row.get("provider_order_id") or "")
        fill_id = str(row.get("id") or row.get("fill_id") or row.get("provider_fill_id") or "")
        identity = (str(row.get("provider") or "UNKNOWN"), order_id, fill_id)
        if identity in seen_fills:
            continue
        seen_fills.add(identity)
        linked_event = next((event for event in events if str(event.get("provider_order_id")) == order_id and str(event.get("local_submission_id")) != "UNKNOWN" and event.get("verification_epoch_id") not in {None, "UNKNOWN"}), None)
        linked = linked_event is not None and fill_id not in {"", "UNKNOWN"}
        if linked:
            owned.append(row)
            symbol = row.get("symbol") or row.get("ticker") or row.get("instrument")
            if symbol is not None:
                linked_symbols.add(str(symbol))
        else:
            unattributed_fills.append(row)
    owned_positions = []
    unattributed_positions = []
    for position in positions:
        symbol = str(position.get("symbol") or position.get("ticker") or position.get("instrument") or "")
        if symbol and symbol in linked_symbols:
            owned_positions.append(position)
        else:
            unattributed_positions.append(position)
    unique_orders = {str(event.get("local_submission_id") or event.get("order_intent_id")) for event in events if event.get("local_submission_id") not in {None, "UNKNOWN"}}
    requested_by_order = {}
    for event in events:
        key = event.get("local_submission_id") or event.get("order_intent_id")
        value = number(event.get("requested_quantity"))
        if key not in {None, "UNKNOWN"} and value:
            requested_by_order.setdefault(str(key), value)
    return {
        "owned_open_positions": owned_positions,
        "unattributed_provider_positions": unattributed_positions,
        "legacy_or_pre_epoch_positions": [],
        "ownership_incomplete_positions": unattributed_positions,
        "working_orders": orders,
        "orders_requested": len(unique_orders),
        "requested_quantity": sum(requested_by_order.values()),
        "filled_quantity": sum(number(row.get("filled_quantity") or row.get("quantity") or row.get("qty")) for row in owned),
        "remaining_quantity": "UNKNOWN", "capital_reserved": "FROM_RESERVATION_LEDGER",
        "capital_releasable": "EXIT_FILL_OR_CONFIRMED_CANCEL_ONLY", "verified_realized_pnl": "UNKNOWN",
        "verified_unrealized_pnl": "UNKNOWN", "incomplete_accounting": not bool(owned),
        "unattributed_provider_activity": unattributed_fills,
        "provider_order_ids_observed": len(order_ids), "provider_fill_ids_observed": len(seen_fills),
    }
