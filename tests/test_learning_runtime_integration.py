import pytest

from autotrader.intelligence_learning import IntelligenceLearningTree, map_market_outcome
from autotrader.learning_runtime import build_integrity, observe_cross_pillar, persist_filing_delta, update_attributions


def test_market_outcome_has_mfe_mae_and_abnormal_return():
    result = map_market_outcome(entry_price=100, benchmark_return=.01, transaction_cost=.001,
                                bars=[{"close": 102, "high": 105, "low": 99}, {"close": 103, "high": 104, "low": 101}])
    assert result["mfe"] == pytest.approx(.05) and result["mae"] == pytest.approx(-.01) and result["abnormal_return"] == pytest.approx(.019)


def test_filing_delta_persists(tmp_path):
    path = tmp_path / "research.db"
    persist_filing_delta(path, current_accession="a", prior_accession="b", feature="RISK_FACTOR_ADDED", direction="UP", magnitude=1, confidence=.9, observed_at="2026-01-01", effective_at="2026-01-01", provenance="fixture")
    import sqlite3
    with sqlite3.connect(path) as conn:
        assert conn.execute("select count(*) from filing_deltas").fetchone()[0] == 1


def test_attribution_and_relationship_runtime_tables(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "research.db")
    tree.schedule(observation_id="x", symbol="ABC", observed_at="2026-01-01T00:00:00+00:00")
    assert update_attributions(tree.path)["families"] == 7
    assert observe_cross_pillar(tree.path, observed_at="2026-01-01T00:00:00+00:00") == 8


def test_integrity_report_is_durable(tmp_path):
    report = build_integrity(tmp_path / "research.db")
    assert report["checks"]["LIVE_TRADING_DISABLED"] == "PASS"


def test_outcome_missing_bars_is_explicit():
    import pytest
    with pytest.raises(ValueError):
        map_market_outcome(entry_price=100, bars=[])
