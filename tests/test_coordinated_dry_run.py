from autotrader.audit import SQLiteAuditStore
from autotrader.coordinated_dry_run import DryRunCandidate, FivePillarDryRunner
from autotrader.models import AssetClass, Side, TradeProposal


def candidate(stop=95.0):
    return DryRunCandidate(
        pillar="alpaca_metals",
        broker="alpaca-metals-paper",
        proposal=TradeProposal("GLD", AssetClass.ETF, Side.BUY, 100.0, stop, 0.8, "dry-run"),
        order_type="market+protective-stop",
        target_price=110.0,
        strategy_version="baseline-scan-v1",
        reason="deterministic candidate fixture",
    )


def test_dry_run_sizes_and_logs_without_broker_dependency(tmp_path):
    audit = SQLiteAuditStore(tmp_path / "audit.db")
    decision = FivePillarDryRunner(audit).run([candidate()])[0]
    assert decision.risk_engine_status == "approved"
    assert decision.quantity == 2.0
    assert decision.notional_exposure == 200.0
    event = audit.recent(event_type="five_pillar_dry_run")[0]
    assert event.data["orders_submitted"] == 0


def test_dry_run_rejects_missing_stop():
    decision = FivePillarDryRunner().run([candidate(stop=0.0)])[0]
    assert decision.risk_engine_status == "rejected"
    assert decision.quantity == 0.0
