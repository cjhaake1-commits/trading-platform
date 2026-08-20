from autotrader.audit import SQLiteAuditStore
from autotrader.coordinated_dry_run import DryRunDecision
from autotrader.execution_preview import preview_execution_pipeline


def test_pipeline_reaches_adapter_boundary_and_stops_without_submission(tmp_path):
    decision = DryRunDecision(
        pillar="alpaca_metals",
        broker="alpaca-metals-paper",
        instrument="GLD",
        side="buy",
        intended_entry=100.0,
        order_type="market+protective-stop",
        quantity=1.0,
        notional_exposure=100.0,
        stop=95.0,
        target=110.0,
        dollars_at_risk=5.0,
        pillar_risk_pct=0.005,
        model_confidence=0.8,
        model_version="five_pillar_baseline_v1",
        strategy_version="baseline-v1",
        risk_engine_status="approved",
        reason="fixture",
    )
    audit = SQLiteAuditStore(tmp_path / "audit.db")

    result = preview_execution_pipeline([decision], audit=audit)

    assert result["orders_submitted"] == 0
    assert result["submission_boundary_enforced"] is True
    assert result["items"][0]["submission_invoked"] is False
    assert result["items"][0]["stages"]["broker_adapter"] == "ready_at_submission_boundary"
    assert audit.recent(event_type="paper_order_pipeline_preview")[0].data["submission_invoked"] is False
