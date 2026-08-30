from datetime import UTC, datetime, timedelta

from autotrader.intelligence_learning import IntelligenceLearningTree


def test_outcome_jobs_are_idempotent_and_resolve_once(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "research.db")
    observed = datetime.now(UTC) - timedelta(days=30)
    assert tree.schedule(observation_id="o1", symbol="ABC", observed_at=observed.isoformat()) == 5
    assert tree.schedule(observation_id="o1", symbol="ABC", observed_at=observed.isoformat()) == 5
    pending = tree.pending()
    assert len(pending) == 5
    assert tree.resolve(observation_id="o1", horizon="1D", return_pct=.02, mfe=.03, mae=-.01)
    assert not tree.resolve(observation_id="o1", horizon="1D", return_pct=.03)


def test_promotion_requires_forward_sample_and_risk_controls():
    assert IntelligenceLearningTree.promotion_status(sample_count=99, forward_count=99, expectancy=1, max_drawdown=0) == ("SHADOW_TESTING", "insufficient forward sample")
    assert IntelligenceLearningTree.promotion_status(sample_count=100, forward_count=50, expectancy=-1, max_drawdown=0)[0] == "REJECTED"
    assert IntelligenceLearningTree.promotion_status(sample_count=100, forward_count=50, expectancy=1, max_drawdown=.1)[0] == "ELIGIBLE_FOR_MODEL"
