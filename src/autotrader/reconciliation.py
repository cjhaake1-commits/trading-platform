from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Iterable

from .models import PortfolioState


@dataclass(frozen=True)
class BrokerPosition:
    broker: str
    symbol: str
    quantity: float
    average_price: float | None = None


@dataclass(frozen=True)
class ReconciliationIssue:
    symbol: str
    kind: str
    ledger_quantity: float
    broker_quantity: float
    reason: str


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    issues: tuple[ReconciliationIssue, ...]
    reason: str


class PositionReconciler:
    """Compare persisted logical positions to broker truth after startup/reconnect.

    Reconciliation is intentionally fail closed. A discrepancy must be resolved
    or explicitly acknowledged before the system can create new exposure.
    """

    def __init__(self, *, quantity_tolerance: float = 1e-8) -> None:
        if quantity_tolerance < 0:
            raise ValueError("quantity_tolerance cannot be negative")
        self.quantity_tolerance = quantity_tolerance

    def reconcile(
        self,
        portfolio: PortfolioState,
        broker_positions: list[BrokerPosition],
    ) -> ReconciliationResult:
        broker_by_symbol: dict[str, float] = {}
        for position in broker_positions:
            broker_by_symbol[position.symbol] = (
                broker_by_symbol.get(position.symbol, 0.0) + position.quantity
            )

        ledger_symbols = set(portfolio.positions)
        broker_symbols = {
            symbol
            for symbol, quantity in broker_by_symbol.items()
            if abs(quantity) > self.quantity_tolerance
        }
        issues: list[ReconciliationIssue] = []

        for symbol in sorted(ledger_symbols | broker_symbols):
            ledger_quantity = (
                portfolio.positions.get(symbol).quantity if symbol in portfolio.positions else 0.0
            )
            broker_quantity = broker_by_symbol.get(symbol, 0.0)
            if isclose(
                ledger_quantity,
                broker_quantity,
                rel_tol=0.0,
                abs_tol=self.quantity_tolerance,
            ):
                continue
            if ledger_quantity == 0:
                kind = "broker_only_position"
                reason = "broker has exposure absent from persistent ledger"
            elif broker_quantity == 0:
                kind = "ledger_only_position"
                reason = "ledger has exposure absent from broker"
            else:
                kind = "quantity_mismatch"
                reason = "broker and ledger quantities disagree"
            issues.append(
                ReconciliationIssue(
                    symbol=symbol,
                    kind=kind,
                    ledger_quantity=ledger_quantity,
                    broker_quantity=broker_quantity,
                    reason=reason,
                )
            )

        if issues:
            return ReconciliationResult(
                False,
                tuple(issues),
                "position reconciliation failed; new exposure must remain blocked",
            )
        return ReconciliationResult(True, (), "broker and ledger positions reconcile")


@dataclass(frozen=True)
class BrokerOrderSnapshot:
    order_id: str
    symbol: str
    status: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    client_order_id: str | None = None
    side: str | None = None
    order_type: str | None = None


@dataclass(frozen=True)
class ManifestClassification:
    manifest_id: str
    symbol: str
    lifecycle_state: str
    reconciliation_status: str
    broker_order_id: str | None
    filled_quantity: float | None
    broker_position_quantity: float | None
    protection_state: str | None = None
    protection_quantity: float | None = None
    resolution_reason: str | None = None
    snapshot_complete: bool = True


UNRESOLVED_MANIFEST_STATES = {
    "approved_manifest",
    "order_submitted",
    "order_pending",
    "filled_position_pending",
    "reconciliation_pending",
    "protection_pending",
    "protection_submitted",
    "reconciliation_deferred",
    "manual_review_required",
}


def classify_unresolved_manifests(
    manifests: Iterable[dict[str, object]],
    orders: Iterable[BrokerOrderSnapshot],
    positions: Iterable[BrokerPosition],
    *,
    positions_snapshot_complete: bool = True,
    open_orders_snapshot_complete: bool = True,
    recent_orders_snapshot_complete: bool = True,
) -> list[ManifestClassification]:
    orders_by_id = {order.order_id: order for order in orders}
    quantity_by_symbol: dict[str, float] = {}
    for position in positions:
        quantity_by_symbol[position.symbol] = (
            quantity_by_symbol.get(position.symbol, 0.0) + position.quantity
        )
    output: list[ManifestClassification] = []
    for manifest in manifests:
        manifest_id = str(manifest.get("manifest_id") or "")
        symbol = str(
            manifest.get("canonical_symbol") or manifest.get("broker_symbol") or ""
        ).upper()
        broker_order_id = str(manifest.get("broker_order_id") or "") or None
        if not manifest_id or not symbol:
            continue
        order = orders_by_id.get(broker_order_id or "")
        lifecycle_state = str(manifest.get("lifecycle_state") or "").lower()
        broker_position_quantity = quantity_by_symbol.get(symbol)
        snapshot_complete = (
            positions_snapshot_complete
            and open_orders_snapshot_complete
            and recent_orders_snapshot_complete
        )
        if order is None:
            if not snapshot_complete:
                output.append(
                    ManifestClassification(
                        manifest_id=manifest_id,
                        symbol=symbol,
                        lifecycle_state="reconciliation_deferred",
                        reconciliation_status="reconciliation_deferred",
                        broker_order_id=broker_order_id,
                        filled_quantity=None,
                        broker_position_quantity=broker_position_quantity,
                        resolution_reason=(
                            "broker snapshot incomplete; order status not yet authoritative"
                        ),
                        snapshot_complete=False,
                    )
                )
            elif broker_position_quantity is None or abs(broker_position_quantity) <= 1e-12:
                output.append(
                    ManifestClassification(
                        manifest_id=manifest_id,
                        symbol=symbol,
                        lifecycle_state="manual_review_required",
                        reconciliation_status="manual_review_required",
                        broker_order_id=broker_order_id,
                        filled_quantity=None,
                        broker_position_quantity=broker_position_quantity,
                        resolution_reason="broker order missing from snapshot",
                        snapshot_complete=snapshot_complete,
                    )
                )
            else:
                output.append(
                    ManifestClassification(
                        manifest_id=manifest_id,
                        symbol=symbol,
                        lifecycle_state="reconciled",
                        reconciliation_status="broker_confirmed",
                        broker_order_id=broker_order_id,
                        filled_quantity=broker_position_quantity,
                        broker_position_quantity=broker_position_quantity,
                        protection_state="pending",
                        protection_quantity=abs(broker_position_quantity),
                        resolution_reason="position visible without matching order snapshot",
                        snapshot_complete=snapshot_complete,
                    )
                )
            continue
        status = str(order.status or "").lower()
        filled_qty = abs(order.filled_qty)
        if not snapshot_complete and filled_qty <= 1e-12 and status not in {
            "canceled",
            "expired",
            "rejected",
        }:
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="reconciliation_deferred",
                    reconciliation_status="reconciliation_deferred",
                    broker_order_id=broker_order_id,
                    filled_quantity=None,
                    broker_position_quantity=broker_position_quantity,
                    resolution_reason="broker snapshot incomplete; reconciliation deferred",
                    snapshot_complete=False,
                )
            )
            continue
        if status in {"canceled", "expired", "rejected"} and filled_qty <= 1e-12:
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="cancelled_unfilled",
                    reconciliation_status="cancelled_unfilled",
                    broker_order_id=broker_order_id,
                    filled_quantity=0.0,
                    broker_position_quantity=0.0,
                    resolution_reason="terminal zero-fill broker order",
                    snapshot_complete=snapshot_complete,
                )
            )
            continue
        if (
            filled_qty > 1e-12
            and broker_position_quantity is not None
            and abs(broker_position_quantity) > 1e-12
        ):
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="active",
                    reconciliation_status="broker_confirmed",
                    broker_order_id=broker_order_id,
                    filled_quantity=filled_qty,
                    broker_position_quantity=broker_position_quantity,
                    protection_state="confirmed",
                    protection_quantity=abs(broker_position_quantity),
                    resolution_reason="filled order reconciled to broker-confirmed position",
                    snapshot_complete=snapshot_complete,
                )
            )
            continue
        if status in {"new", "accepted", "held", "pending_new", "calculated"} and (
            filled_qty <= 1e-12
        ):
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="order_pending",
                    reconciliation_status="order_pending",
                    broker_order_id=broker_order_id,
                    filled_quantity=0.0,
                    broker_position_quantity=broker_position_quantity,
                    resolution_reason="open zero-fill order remains pending",
                    snapshot_complete=snapshot_complete,
                )
            )
            continue
        if filled_qty > 1e-12 and (
            broker_position_quantity is None or abs(broker_position_quantity) <= 1e-12
        ):
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="filled_position_pending",
                    reconciliation_status="filled_position_pending",
                    broker_order_id=broker_order_id,
                    filled_quantity=filled_qty,
                    broker_position_quantity=broker_position_quantity,
                    resolution_reason="filled order awaiting visible broker position",
                    snapshot_complete=snapshot_complete,
                )
            )
            continue
        if not snapshot_complete:
            output.append(
                ManifestClassification(
                    manifest_id=manifest_id,
                    symbol=symbol,
                    lifecycle_state="reconciliation_deferred",
                    reconciliation_status="reconciliation_deferred",
                    broker_order_id=broker_order_id,
                    filled_quantity=filled_qty if filled_qty > 0 else None,
                    broker_position_quantity=broker_position_quantity,
                    resolution_reason=(
                        "broker snapshot incomplete; reconciliation deferred"
                    ),
                    snapshot_complete=False,
                )
            )
            continue
        output.append(
            ManifestClassification(
                manifest_id=manifest_id,
                symbol=symbol,
                lifecycle_state="manual_review_required",
                reconciliation_status="manual_review_required",
                broker_order_id=broker_order_id,
                filled_quantity=filled_qty if filled_qty > 0 else None,
                broker_position_quantity=broker_position_quantity,
                resolution_reason=f"unsupported lifecycle {lifecycle_state} / status {status}",
                snapshot_complete=snapshot_complete,
            )
        )
    return output


def _canonical_alpaca_symbol(row: dict[str, object]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    asset_class = str(row.get("asset_class") or "").lower()
    if asset_class == "crypto" and "/" not in symbol:
        for quote in ("USD", "USDT", "USDC"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return f"{symbol[:-len(quote)]}/{quote}"
    return symbol


def normalize_alpaca_positions(records: object) -> list[BrokerPosition]:
    if not isinstance(records, list):
        return []
    output: list[BrokerPosition] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        qty = row.get("qty")
        if symbol is None or qty is None:
            continue
        side = str(row.get("side") or "long").lower()
        quantity = float(qty)
        if side == "short":
            quantity = -abs(quantity)
        output.append(
            BrokerPosition(
                broker="alpaca-paper",
                symbol=_canonical_alpaca_symbol(row),
                quantity=quantity,
                average_price=(
                    None
                    if row.get("avg_entry_price") is None
                    else float(row["avg_entry_price"])
                ),
            )
        )
    return output


def normalize_oanda_positions(records: object) -> list[BrokerPosition]:
    if not isinstance(records, list):
        return []
    output: list[BrokerPosition] = []
    for row in records:
        if not isinstance(row, dict) or row.get("instrument") is None:
            continue
        symbol = str(row["instrument"]).replace("_", "/").upper()
        long = row.get("long") if isinstance(row.get("long"), dict) else {}
        short = row.get("short") if isinstance(row.get("short"), dict) else {}
        long_units = float(long.get("units", 0) or 0)
        short_units = float(short.get("units", 0) or 0)
        quantity = long_units + short_units
        average = long.get("averagePrice") if quantity >= 0 else short.get("averagePrice")
        if abs(quantity) <= 1e-12:
            continue
        output.append(
            BrokerPosition(
                broker="oanda-practice",
                symbol=symbol,
                quantity=quantity,
                average_price=None if average is None else float(average),
            )
        )
    return output
