from autotrader.research_platform import ResearchStore, classify_readiness, compounding_decision


def test_research_store_persists_records_and_forces_broker_control_off(tmp_path):
    store = ResearchStore(tmp_path / "research.db")
    store.put_research({"research_id": "etf-1", "lane": "etf", "source": "fixture", "metadata_json": {"return_1m": 0.02}, "promotion_status": "REVIEW"})
    row = store.research("etf")[0]
    assert row["research_id"] == "etf-1"
    assert row["broker_control"] == 0


def test_cash_bucket_compounding_never_changes_authorized_start(tmp_path):
    store = ResearchStore(tmp_path / "research.db")
    store.put_cash("five_pillar_paper_v2", net_realized_cash=125, capital_deployed=500)
    with store.connection() as conn:
        row = conn.execute("SELECT * FROM cash_buckets").fetchone()
    assert row[1] == 5000
    assert row[10] == 5125


def test_readiness_requires_meaningful_evidence():
    assert classify_readiness(paper_days=10, completed_trades=2, expectancy=1, profit_factor=2, drawdown=0.01, execution_failures=0, reconciliation_failures=0, model_stability=True, broker_reliability=True) == "COLLECTING_EVIDENCE"
    assert classify_readiness(paper_days=40, completed_trades=120, expectancy=1, profit_factor=1.2, drawdown=0.05, execution_failures=0, reconciliation_failures=0, model_stability=True, broker_reliability=True) == "PAPER_VALIDATED"


def test_compounding_is_bounded_and_evidence_gated():
    assert compounding_decision(expectancy=10, drawdown=0.01, volatility=0.01, sample_size=2, capital_efficiency=1, confidence=1) == "RETAIN"
    assert compounding_decision(expectancy=10, drawdown=0.01, volatility=0.01, sample_size=40, capital_efficiency=1, confidence=1) == "REDEPLOY"
