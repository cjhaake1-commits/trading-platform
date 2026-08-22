from autotrader.research_jobs import DailyReportJob, ResearchRefreshJob
from autotrader.research_platform import (
    ResearchStore,
    classify_readiness,
    classify_regime,
    compounding_decision,
    evaluate_shadow_hedge,
    normalize_disclosure,
    performance_metrics,
)
from autotrader.short_safety import evaluate_paper_short


def test_research_store_persists_records_and_forces_broker_control_off(tmp_path):
    store = ResearchStore(tmp_path / "research.db")
    store.put_research(
        {
            "research_id": "etf-1",
            "lane": "etf",
            "source": "fixture",
            "metadata_json": {"return_1m": 0.02},
            "promotion_status": "REVIEW",
        }
    )
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
    assert (
        classify_readiness(
            paper_days=10,
            completed_trades=2,
            expectancy=1,
            profit_factor=2,
            drawdown=0.01,
            execution_failures=0,
            reconciliation_failures=0,
            model_stability=True,
            broker_reliability=True,
        )
        == "COLLECTING_EVIDENCE"
    )
    assert (
        classify_readiness(
            paper_days=40,
            completed_trades=120,
            expectancy=1,
            profit_factor=1.2,
            drawdown=0.05,
            execution_failures=0,
            reconciliation_failures=0,
            model_stability=True,
            broker_reliability=True,
        )
        == "PAPER_VALIDATED"
    )


def test_compounding_is_bounded_and_evidence_gated():
    assert (
        compounding_decision(
            expectancy=10, drawdown=0.01, volatility=0.01, sample_size=2, capital_efficiency=1, confidence=1
        )
        == "RETAIN"
    )
    assert (
        compounding_decision(
            expectancy=10, drawdown=0.01, volatility=0.01, sample_size=40, capital_efficiency=1, confidence=1
        )
        == "REDEPLOY"
    )


def test_etf_metrics_are_deterministic_and_require_history():
    metrics = performance_metrics([100 + i for i in range(300)])
    assert metrics["return_1m"] is not None
    assert metrics["max_drawdown"] == 0
    assert performance_metrics([100])["return_1m"] is None


def test_disclosures_are_delayed_research_only():
    record = normalize_disclosure(
        lane="politician",
        source="fixture",
        source_url="https://example.test",
        as_of_date="2026-01-01",
        payload={"asset": "ETF", "delay_days": 30},
    )
    assert record["freshness"] == "DELAYED"
    assert record["broker_control"] == 0


def test_regime_and_shadow_hedge_are_bounded():
    assert classify_regime(return_pct=0.05, volatility=0.02, trend_strength=0.8) == "risk_on"
    hedge = evaluate_shadow_hedge(overnight_direction=-0.02, gap_pct=0.06, volatility=0.03, portfolio_concentration=0.8)
    assert hedge["mode"] == "SHADOW_ONLY"
    assert 0 <= hedge["recommended_size"] <= 0.1


def test_research_and_daily_jobs_are_independent_and_durable(tmp_path):
    path = tmp_path / "research.db"
    assert ResearchRefreshJob(str(path)).run(__import__("datetime").datetime.now(__import__("datetime").UTC)).ok
    result = DailyReportJob(str(path)).run(__import__("datetime").datetime.now(__import__("datetime").UTC))
    assert result.ok
    with ResearchStore(path).connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0] == 1


def test_feature_attribution_is_durable_and_short_gates_fail_closed(tmp_path):
    store = ResearchStore(tmp_path / "research.db")
    store.put_attribution(
        observation_id="o1",
        feature_name="momentum",
        feature_value=0.4,
        feature_source="fixture",
        feature_freshness="FRESH",
        feature_weight=0.5,
        regime="trending",
        model="baseline",
        decision="SHORT",
    )
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM feature_attribution").fetchone()[0] == 1
    result = evaluate_paper_short(
        environment="PAPER",
        shortable=False,
        borrow_available=False,
        liquidity_ok=True,
        spread_ok=True,
        session_open=True,
        same_symbol_conflict=False,
        available_capital=1000,
        required_capital=100,
        risk_approved=True,
    )
    assert not result.allowed
    assert "shortable" in result.reason
