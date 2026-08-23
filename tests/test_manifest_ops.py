from datetime import UTC, datetime

from autotrader.manifest_ops import ManifestCategory, classify_manifest
from autotrader.portfolio_ledger import PortfolioLedger


def _manifest(**overrides):
    row = {"manifest_id": "m1", "canonical_symbol": "MSTR", "broker_order_id": "o1", "lifecycle_state": "reconciliation_deferred", "created_at": "2026-01-01T00:00:00+00:00"}
    row.update(overrides)
    return row


def test_historical_manifest_is_archivable_without_deleting_source():
    disposition = classify_manifest(_manifest(), experiment_start=datetime(2026, 2, 1, tzinfo=UTC))
    assert disposition.category is ManifestCategory.ARCHIVABLE_HISTORICAL


def test_current_broker_evidence_keeps_manifest_active():
    disposition = classify_manifest(_manifest(), experiment_start=datetime(2025, 1, 1, tzinfo=UTC), open_order_ids=["o1"])
    assert disposition.category is ManifestCategory.LEGITIMATE_ACTIVE


def test_archive_is_append_only(tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.connection = None
    with ledger._connect() as conn:
        conn.execute("INSERT INTO entry_manifests (manifest_id,created_at,broker,environment,pillar,canonical_symbol,broker_symbol,side,model_version,strategy_version,confidence,regime,approved_entry,requested_quantity,approved_notional,approved_stop,approved_dollar_risk,allocation_at_approval,portfolio_risk_at_approval,risk_engine_decision,lifecycle_state,client_order_id_namespace,fingerprint,updated_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("m1","now","alpaca","paper","Stocks","MSTR","MSTR","buy","m","s",1,None,1,1,1,1,1,1,1,"approved","reconciliation_deferred","ns","fp","now","{}"))
    ledger.archive_manifest("m1", category="ARCHIVABLE_HISTORICAL", reason="old", evidence=["no broker evidence"])
    with ledger._connect() as conn:
        assert conn.execute("select count(*) from entry_manifests").fetchone()[0] == 1
        assert conn.execute("select count(*) from manifest_archive").fetchone()[0] == 1
