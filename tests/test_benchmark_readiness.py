from __future__ import annotations

from autotrader.benchmark_readiness import (
    DEFAULT_BENCHMARKS,
    BenchmarkReadinessPolicy,
    PaperPerformanceEvidence,
    assess_benchmark_readiness,
)


def evidence(**overrides):
    base = {
        "observation_days": 180,
        "completed_trades": 180,
        "observed_market_regimes": 4,
        "data_coverage": 0.99,
        "strategy_total_return": 0.35,
        "strategy_max_drawdown": 0.08,
        "benchmark_total_returns": {"sp500_index": 0.12, "qqq": 0.16, "vti": 0.11, "vfiax": 0.12},
        "benchmark_max_drawdowns": {"sp500_index": 0.10, "qqq": 0.13, "vti": 0.10, "vfiax": 0.10},
        "rolling_strategy_returns": tuple([0.04] * 16),
        "rolling_benchmark_returns": {
            "sp500_index": tuple([0.01] * 16),
            "qqq": tuple([0.02] * 16),
            "vti": tuple([0.01] * 16),
            "vfiax": tuple([0.01] * 16),
        },
        "accounting_verified": True,
        "cost_model_complete": True,
        "stress_tests_passed": True,
        "data_lineage_complete": True,
    }
    base.update(overrides)
    return PaperPerformanceEvidence(**base)


def test_catalog_has_indices_etfs_mutual_funds_and_crypto():
    categories = {item.category for item in DEFAULT_BENCHMARKS}
    assert {"index", "etf", "mutual_fund", "crypto"}.issubset(categories)
    assert any(item.bloomberg_security == "SPX Index" for item in DEFAULT_BENCHMARKS)


def test_insufficient_history_remains_learning():
    result = assess_benchmark_readiness(evidence(observation_days=30, completed_trades=20))
    assert result.state == "LEARNING"
    assert result.live_transition_allowed is False
    assert any("paper history" in reason for reason in result.reasons)


def test_unverified_accounting_blocks_readiness():
    result = assess_benchmark_readiness(evidence(accounting_verified=False))
    assert result.state == "BLOCKED_DATA_INTEGRITY"
    assert result.live_transition_allowed is False


def test_underperformance_remains_developing():
    result = assess_benchmark_readiness(
        evidence(
            strategy_total_return=0.08,
            rolling_strategy_returns=tuple([0.005] * 16),
        )
    )
    assert result.state == "BENCHMARK_DEVELOPING"
    assert result.benchmark_outperformance_ratio == 0.0


def test_consistent_paper_outperformance_never_auto_enables_live():
    result = assess_benchmark_readiness(evidence())
    assert result.state == "PAPER_EDGE_CONFIRMED"
    assert result.benchmark_outperformance_ratio == 1.0
    assert result.rolling_outperformance_ratio == 1.0
    assert result.live_transition_allowed is False
    assert result.human_approval_required is True


def test_drawdown_worse_than_policy_fails_even_with_high_return():
    result = assess_benchmark_readiness(evidence(strategy_max_drawdown=0.30))
    assert result.state == "BENCHMARK_DEVELOPING"
    assert any("drawdown" in reason for reason in result.reasons)


def test_policy_is_configurable_but_defaults_to_six_months():
    policy = BenchmarkReadinessPolicy.from_env(
        {
            "LIVE_READINESS_MIN_PAPER_DAYS": "252",
            "LIVE_READINESS_MIN_COMPLETED_TRADES": "250",
            "LIVE_READINESS_MIN_ROLLING_OUTPERFORMANCE": "0.8",
        }
    )
    assert BenchmarkReadinessPolicy().minimum_observation_days == 126
    assert policy.minimum_observation_days == 252
    assert policy.minimum_completed_trades == 250
    assert policy.minimum_rolling_outperformance_ratio == 0.8
