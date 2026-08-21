from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from .brokers.safety import (
    BrokerRequestBudget,
    _alpaca_api_symbol,
    _alpaca_auth,
    _alpaca_headers,
    _request,
)
from .portfolio_ledger import PortfolioLedger
from .reconciliation import (
    BrokerOrderSnapshot,
    BrokerPosition,
    ManifestClassification,
    classify_unresolved_manifests,
)


def _utc_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class AlpacaBulkSnapshot:
    positions: tuple[BrokerPosition, ...]
    open_orders: tuple[BrokerOrderSnapshot, ...]
    recent_orders: tuple[BrokerOrderSnapshot, ...]
    budget: BrokerRequestBudget
    window_start: datetime | None
    window_end: datetime | None
    positions_snapshot_complete: bool = False
    open_orders_snapshot_complete: bool = False
    recent_orders_snapshot_complete: bool = False
    deferred: bool = False

    @property
    def orders_by_id(self) -> dict[str, BrokerOrderSnapshot]:
        orders = {order.order_id: order for order in (*self.open_orders, *self.recent_orders)}
        return orders

    @property
    def orders_by_symbol(self) -> dict[str, list[BrokerOrderSnapshot]]:
        by_symbol: dict[str, list[BrokerOrderSnapshot]] = {}
        for order in (*self.open_orders, *self.recent_orders):
            by_symbol.setdefault(order.symbol, []).append(order)
        return by_symbol


@dataclass(frozen=True)
class AlpacaBacklogResult:
    dry_run: bool
    classifications: tuple[ManifestClassification, ...]
    telemetry: dict[str, int]
    duplicate_orders_cancelled: tuple[str, ...]
    unresolved_before: int
    unresolved_after: int


def _canonical_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("_", "/")
    if "/" in normalized:
        return normalized
    for quote in ("USD", "USDT", "USDC"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return f"{normalized[:-len(quote)]}/{quote}"
    return normalized


def _is_managed(order: BrokerOrderSnapshot) -> bool:
    client = (order.client_order_id or "").strip().lower()
    return client.startswith("auto-")


def _parse_position(row: dict[str, object]) -> BrokerPosition | None:
    symbol = row.get("symbol")
    qty = row.get("qty")
    if symbol is None or qty is None:
        return None
    side = str(row.get("side") or "long").lower()
    quantity = float(qty)
    if side == "short":
        quantity = -abs(quantity)
    return BrokerPosition(
        broker="alpaca-paper",
        symbol=_canonical_symbol(str(symbol)),
        quantity=quantity,
        average_price=(
            None if row.get("avg_entry_price") is None else float(row["avg_entry_price"])
        ),
    )


def _parse_order(row: dict[str, object]) -> BrokerOrderSnapshot | None:
    order_id = str(row.get("id") or "")
    symbol = str(row.get("symbol") or "")
    if not order_id or not symbol:
        return None
    return BrokerOrderSnapshot(
        order_id=order_id,
        symbol=_canonical_symbol(symbol),
        status=str(row.get("status") or ""),
        filled_qty=abs(float(row.get("filled_qty") or 0.0)),
        filled_avg_price=(
            None if row.get("filled_avg_price") is None else float(row["filled_avg_price"])
        ),
        client_order_id=str(row.get("client_order_id") or "") or None,
        side=str(row.get("side") or "") or None,
        order_type=str(row.get("type") or "") or None,
    )


def fetch_alpaca_bulk_snapshot(
    unresolved_manifests: Iterable[dict[str, object]],
    *,
    request_fn: Callable[..., tuple[object, dict[str, str]]] = _request,
    budget_limit: int = 12,
) -> AlpacaBulkSnapshot:
    key, secret, base = _alpaca_auth()
    budget = BrokerRequestBudget(limit=budget_limit)
    manifests = list(unresolved_manifests)
    if not manifests:
        return AlpacaBulkSnapshot((), (), (), budget, None, None)

    created_times: list[datetime] = []
    for manifest in manifests:
        created_at = str(manifest.get("created_at") or "")
        if not created_at:
            continue
        try:
            created_times.append(
                datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
            )
        except ValueError:
            continue
    window_start = min(created_times) - timedelta(days=1) if created_times else None
    window_end = max(created_times) + timedelta(days=1) if created_times else None

    deferred = False
    positions_complete = False
    open_orders_complete = False
    recent_orders_complete = False
    try:
        _consume_budget(budget)
        positions_payload, _ = request_fn(
            f"{base}/v2/positions",
            method="GET",
            headers=_alpaca_headers(key, secret),
            budget=budget,
        )
    except RuntimeError:
        budget.note_rate_limit(deferred=True)
        deferred = True
        positions_payload = []
    else:
        positions_complete = True
    try:
        _consume_budget(budget)
        open_orders_payload, _ = request_fn(
            f"{base}/v2/orders?status=open&nested=true&limit=500",
            method="GET",
            headers=_alpaca_headers(key, secret),
            budget=budget,
        )
    except RuntimeError:
        budget.note_rate_limit(deferred=True)
        deferred = True
        open_orders_payload = []
    else:
        open_orders_complete = True
    recent_query = ["status=all", "nested=true", "limit=500"]
    if window_start is not None:
        recent_query.append(f"after={_utc_iso(window_start)}")
    if window_end is not None:
        recent_query.append(f"until={_utc_iso(window_end)}")
    try:
        _consume_budget(budget)
        recent_orders_payload, _ = request_fn(
            f"{base}/v2/orders?{'&'.join(recent_query)}",
            method="GET",
            headers=_alpaca_headers(key, secret),
            budget=budget,
        )
    except RuntimeError:
        budget.note_rate_limit(deferred=True)
        deferred = True
        recent_orders_payload = []
    else:
        recent_orders_complete = True

    positions = tuple(_parse_position(row) for row in positions_payload if isinstance(row, dict))
    positions = tuple(row for row in positions if row is not None)
    open_orders = tuple(_parse_order(row) for row in open_orders_payload if isinstance(row, dict))
    open_orders = tuple(row for row in open_orders if row is not None)
    recent_orders = tuple(
        _parse_order(row) for row in recent_orders_payload if isinstance(row, dict)
    )
    recent_orders = tuple(row for row in recent_orders if row is not None)
    return AlpacaBulkSnapshot(
        positions,
        open_orders,
        recent_orders,
        budget,
        window_start,
        window_end,
        positions_complete,
        open_orders_complete,
        recent_orders_complete,
        deferred,
    )


def reconcile_alpaca_equity_backlog(
    ledger_path: str | Path,
    *,
    apply_paper_cleanup: bool = False,
    request_fn: Callable[..., tuple[object, dict[str, str]]] = _request,
    budget_limit: int = 12,
) -> AlpacaBacklogResult:
    ledger = PortfolioLedger(ledger_path)
    key, secret, base = _alpaca_auth()
    unresolved = [
        manifest
        for manifest in ledger.unresolved_entry_manifests(broker="alpaca-paper")
        if str(manifest.get("pillar") or "").lower() not in {"crypto", "forex", "international"}
    ]
    snapshot = fetch_alpaca_bulk_snapshot(
        unresolved,
        request_fn=request_fn,
        budget_limit=budget_limit,
    )
    classifications = classify_unresolved_manifests(
        unresolved,
        snapshot.orders_by_id.values(),
        snapshot.positions,
        positions_snapshot_complete=snapshot.positions_snapshot_complete,
        open_orders_snapshot_complete=snapshot.open_orders_snapshot_complete,
        recent_orders_snapshot_complete=snapshot.recent_orders_snapshot_complete,
    )

    resolved = 0
    pending = 0
    manual = 0
    cancelled_ids: list[str] = []

    grouped_orders: dict[str, list[BrokerOrderSnapshot]] = {}
    for order in snapshot.open_orders:
        grouped_orders.setdefault(order.symbol, []).append(order)

    position_symbols = {
        position.symbol
        for position in snapshot.positions
        if abs(position.quantity) > 1e-12
    }
    for symbol, orders in grouped_orders.items():
        managed = [order for order in orders if _is_managed(order)]
        if len(managed) <= 1 or symbol in position_symbols:
            continue
        for order in managed:
            if not apply_paper_cleanup:
                continue
            try:
                _, _ = request_fn(
                    f"{base}/v2/orders/{order.order_id}",
                    method="DELETE",
                    headers=_alpaca_headers(key, secret),
                    budget=snapshot.budget,
                )
                cancelled_ids.append(order.order_id)
            except Exception:
                manual += 1
                continue

    if apply_paper_cleanup and cancelled_ids:
        try:
            _consume_budget(budget)
            refreshed_payload, _ = request_fn(
                f"{base}/v2/orders?status=all&nested=true&limit=500",
                method="GET",
                headers=_alpaca_headers(key, secret),
                budget=snapshot.budget,
            )
        except RuntimeError:
            budget.note_rate_limit(deferred=True)
            refreshed_payload = []
        recent_orders = tuple(
            _parse_order(row) for row in refreshed_payload if isinstance(row, dict)
        )
        recent_orders = tuple(row for row in recent_orders if row is not None)
        snapshot = AlpacaBulkSnapshot(
            snapshot.positions,
            snapshot.open_orders,
            recent_orders,
            snapshot.budget,
            snapshot.window_start,
            snapshot.window_end,
            snapshot.positions_snapshot_complete,
            snapshot.open_orders_snapshot_complete,
            True,
            snapshot.deferred,
        )
        classifications = classify_unresolved_manifests(
            unresolved,
            snapshot.orders_by_id.values(),
            snapshot.positions,
            positions_snapshot_complete=snapshot.positions_snapshot_complete,
            open_orders_snapshot_complete=snapshot.open_orders_snapshot_complete,
            recent_orders_snapshot_complete=snapshot.recent_orders_snapshot_complete,
        )

    for classification in classifications:
        manifest = ledger.load_entry_manifest(classification.manifest_id)
        if manifest is None:
            manual += 1
            continue
        if classification.lifecycle_state == "cancelled_unfilled":
            resolved += 1
        elif classification.lifecycle_state in {"order_pending", "filled_position_pending"}:
            pending += 1
        elif classification.lifecycle_state in {
            "manual_review_required",
            "reconciliation_deferred",
        }:
            manual += 1
        else:
            resolved += 1
        if not apply_paper_cleanup:
            continue
        _persist_manifest_resolution(ledger, manifest, classification)

    telemetry = {
        "broker_requests": snapshot.budget.requests,
        "broker_retries": snapshot.budget.retries,
        "broker_rate_limited": snapshot.budget.rate_limited,
        "broker_deferred": snapshot.budget.deferred,
        "manifests_processed": len(classifications),
        "manifests_resolved": resolved,
        "manifests_pending": pending,
        "manifests_manual_review": manual,
        "manifests_deferred": sum(
            1 for item in classifications if item.lifecycle_state == "reconciliation_deferred"
        ),
        "duplicate_orders_cancelled": len(cancelled_ids),
    }
    return AlpacaBacklogResult(
        dry_run=not apply_paper_cleanup,
        classifications=tuple(classifications),
        telemetry=telemetry,
        duplicate_orders_cancelled=tuple(cancelled_ids),
        unresolved_before=len(unresolved),
        unresolved_after=pending + manual,
    )


def _persist_manifest_resolution(
    ledger: PortfolioLedger,
    manifest: dict[str, object],
    classification: ManifestClassification,
) -> None:
    close_ids = manifest.get("close_order_ids")
    ledger.save_entry_manifest(
        manifest_id=str(manifest.get("manifest_id")),
        created_at=_utc_datetime(manifest.get("created_at")),
        broker=str(manifest.get("broker")),
        environment=str(manifest.get("environment")),
        pillar=str(manifest.get("pillar")),
        canonical_symbol=str(manifest.get("canonical_symbol")),
        broker_symbol=str(manifest.get("broker_symbol")),
        side=str(manifest.get("side")),
        model_version=str(manifest.get("model_version")),
        strategy_version=str(manifest.get("strategy_version")),
        confidence=float(manifest.get("confidence") or 0.0),
        regime=manifest.get("regime"),
        approved_entry=float(manifest.get("approved_entry") or 0.0),
        requested_quantity=float(manifest.get("requested_quantity") or 0.0),
        approved_notional=float(manifest.get("approved_notional") or 0.0),
        approved_stop=float(manifest.get("approved_stop") or 0.0),
        approved_target=(
            None
            if manifest.get("approved_target") is None
            else float(manifest.get("approved_target"))
        ),
        approved_dollar_risk=float(manifest.get("approved_dollar_risk") or 0.0),
        allocation_at_approval=float(manifest.get("allocation_at_approval") or 0.0),
        portfolio_risk_at_approval=float(manifest.get("portfolio_risk_at_approval") or 0.0),
        risk_engine_decision=str(manifest.get("risk_engine_decision") or ""),
        lifecycle_state=classification.lifecycle_state,
        client_order_id_namespace=str(manifest.get("client_order_id_namespace") or ""),
        fingerprint=str(manifest.get("fingerprint") or ""),
        broker_order_id=classification.broker_order_id or manifest.get("broker_order_id"),
        submitted_quantity=_as_float(manifest.get("submitted_quantity")),
        filled_quantity=classification.filled_quantity,
        broker_confirmed_position_quantity=classification.broker_position_quantity,
        average_fill_price=_as_float(manifest.get("average_fill_price")),
        reconciliation_status=classification.reconciliation_status,
        reconciliation_difference=_as_float(manifest.get("reconciliation_difference")),
        protection_order_id=manifest.get("protection_order_id"),
        protection_quantity=classification.protection_quantity,
        protection_stop=_as_float(manifest.get("protection_stop")),
        protection_state=classification.protection_state,
        close_order_ids=[] if not isinstance(close_ids, list) else close_ids,
        realized_pnl=_as_float(manifest.get("realized_pnl")),
        fees_costs=_as_float(manifest.get("fees_costs")),
        closed_at=(
            None
            if manifest.get("closed_at") is None
            else _utc_datetime(manifest.get("closed_at"))
        ),
        metadata=_manifest_metadata(manifest, classification),
    )


def _manifest_metadata(
    manifest: dict[str, object],
    classification: ManifestClassification,
) -> dict[str, object]:
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = dict(metadata)
    metadata["reconciliation_resolution"] = classification.resolution_reason
    metadata["reconciliation_run_state"] = classification.lifecycle_state
    return metadata


def _utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _consume_budget(budget: BrokerRequestBudget) -> None:
    try:
        budget.consume()
    except RuntimeError:
        budget.note_rate_limit(deferred=True)
        raise
