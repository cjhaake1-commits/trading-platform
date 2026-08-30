import pytest

from autotrader.intelligence_learning import IntelligenceLearningTree, map_market_outcome
from autotrader.learning_runtime import (
    build_integrity,
    observe_cross_pillar,
    persist_filing_delta,
    resolve_ohlc_job,
    semantic_fact_deltas,
    update_attributions,
)


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


def test_semantic_structured_filing_delta(tmp_path):
    assert semantic_fact_deltas({"inventory": 12}, {"inventory": 10}, current_accession="a", prior_accession="b", db_path=tmp_path / "x.db", observed_at="now") == 1


def test_ohlc_job_resolves_and_missing_is_retry(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "r.db")
    tree.schedule(observation_id="o", symbol="ABC", observed_at="2020-01-01T00:00:00+00:00")
    assert resolve_ohlc_job(tree, observation_id="o", horizon="30M", entry_price=100, bars=[{"close": 102, "high": 103, "low": 99}])
    assert not resolve_ohlc_job(tree, observation_id="missing", horizon="30M", entry_price=100, bars=[])


def test_public_resolver_uses_chronological_ohlc_and_leaves_scalar_only_pending(tmp_path):
    import sqlite3
    tree = IntelligenceLearningTree(tmp_path / "r.db")
    tree.schedule(observation_id="o", symbol="ABC", observed_at="2020-01-01T00:00:00+00:00", metadata={"entry_price": 100})
    with sqlite3.connect(tmp_path / "p.db") as con:
        con.execute("create table observations(symbol text,value real,source_time text)")
        con.execute("insert into observations values ('ABC', 110, '2020-01-01T01:00:00+00:00')")
    assert tree.resolve_from_public_store(tmp_path / "p.db", now=__import__('datetime').datetime(2020, 1, 2, tzinfo=__import__('datetime').timezone.utc))["resolved"] == 0


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
