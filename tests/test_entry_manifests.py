from datetime import UTC, datetime

from autotrader.portfolio_ledger import PortfolioLedger


def test_entry_manifest_persists_approval_and_actual_fields(tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    manifest_payload = {
        "broker": "alpaca-paper",
        "environment": "paper",
        "pillar": "Stocks",
        "canonical_symbol": "SPY",
        "broker_symbol": "SPY",
        "side": "buy",
        "model_version": "five_pillar_baseline_v1",
        "strategy_version": "baseline-v1",
        "confidence": 0.81,
        "regime": "trend",
        "approved_entry": 100.0,
        "requested_quantity": 1.0,
        "approved_notional": 100.0,
        "approved_stop": 95.0,
        "approved_target": 110.0,
        "approved_dollar_risk": 5.0,
        "allocation_at_approval": 0.0,
        "portfolio_risk_at_approval": 0.0,
        "risk_engine_decision": "approved",
        "lifecycle_state": "approved_manifest",
        "client_order_id_namespace": "auto-20260820-SPY",
        "fingerprint": ledger.manifest_fingerprint({"canonical_symbol": "SPY", "approved_entry": 100.0}),
    }

    ledger.save_entry_manifest(
        manifest_id="manifest-1",
        created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        metadata={"purpose": "unit-test"},
        **manifest_payload,
    )

    record = ledger.load_entry_manifest("manifest-1")
    assert record is not None
    assert record["approved_stop"] == 95.0
    assert record["lifecycle_state"] == "approved_manifest"
    assert record["fingerprint"] == manifest_payload["fingerprint"]
    assert record["metadata"] == {"purpose": "unit-test"}
