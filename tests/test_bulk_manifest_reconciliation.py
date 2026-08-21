from __future__ import annotations

from autotrader.reconciliation import (
    BrokerOrderSnapshot,
    BrokerPosition,
    classify_unresolved_manifests,
)


def test_terminal_zero_fill_becomes_cancelled_unfilled():
    result = classify_unresolved_manifests(
        [
            {
                "manifest_id": "m1",
                "canonical_symbol": "MSTR",
                "broker_order_id": "o1",
                "lifecycle_state": "order_submitted",
            }
        ],
        [BrokerOrderSnapshot(order_id="o1", symbol="MSTR", status="canceled", filled_qty=0.0)],
        [],
    )
    assert result[0].lifecycle_state == "cancelled_unfilled"
    assert result[0].reconciliation_status == "cancelled_unfilled"


def test_open_zero_fill_remains_pending():
    result = classify_unresolved_manifests(
        [
            {
                "manifest_id": "m1",
                "canonical_symbol": "MSTR",
                "broker_order_id": "o1",
                "lifecycle_state": "order_pending",
            }
        ],
        [BrokerOrderSnapshot(order_id="o1", symbol="MSTR", status="new", filled_qty=0.0)],
        [],
    )
    assert result[0].lifecycle_state == "order_pending"


def test_filled_position_confirms_active():
    result = classify_unresolved_manifests(
        [
            {
                "manifest_id": "m1",
                "canonical_symbol": "ETH/USD",
                "broker_order_id": "o1",
                "lifecycle_state": "filled_position_pending",
            }
        ],
        [BrokerOrderSnapshot(order_id="o1", symbol="ETH/USD", status="filled", filled_qty=1.5)],
        [
            BrokerPosition(
                broker="alpaca-paper",
                symbol="ETH/USD",
                quantity=1.5,
                average_price=100.0,
            )
        ],
    )
    assert result[0].lifecycle_state == "active"
    assert result[0].protection_state == "confirmed"


def test_missing_broker_order_requires_manual_review_when_snapshot_complete():
    result = classify_unresolved_manifests(
        [
            {
                "manifest_id": "m1",
                "canonical_symbol": "MSTR",
                "broker_order_id": "missing",
                "lifecycle_state": "order_submitted",
            }
        ],
        [],
        [],
    )
    assert result[0].lifecycle_state == "manual_review_required"


def test_missing_broker_order_deferred_when_recent_snapshot_incomplete():
    result = classify_unresolved_manifests(
        [
            {
                "manifest_id": "m1",
                "canonical_symbol": "MSTR",
                "broker_order_id": "missing",
                "lifecycle_state": "order_submitted",
            }
        ],
        [],
        [],
        recent_orders_snapshot_complete=False,
    )
    assert result[0].lifecycle_state == "reconciliation_deferred"
    assert result[0].snapshot_complete is False
