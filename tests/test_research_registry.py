from datetime import UTC, datetime

import pytest

from autotrader.research_registry import (
    PromotionPolicy,
    ResearchLane,
    ResearchRegistry,
    ResearchSignal,
    ValidationMetrics,
)


def test_research_signal_rejects_lookahead_timestamp():
    generated = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="information"):
        ResearchSignal(
            lane=ResearchLane.QLIB,
            model_id="alpha158-xgb",
            symbol="SPY",
            score=0.2,
            confidence=0.7,
            horizon_seconds=300,
            generated_at=generated,
            information_available_at=generated.replace(minute=1),
            source_version="test",
        )


def test_challenger_requires_incremental_edge_before_paper():
    registry = ResearchRegistry(PromotionPolicy(min_observations=10))
    registry.register(ResearchLane.RD_AGENT, "factor-001", "commit-abc")
    registry.record_metrics(
        ResearchLane.RD_AGENT,
        "factor-001",
        ValidationMetrics(
            observations=20,
            net_return_pct=2.0,
            max_drawdown_pct=3.0,
            incremental_net_return_pct=-0.1,
        ),
    )
    assert not registry.eligible_for_paper(ResearchLane.RD_AGENT, "factor-001")


def test_challenger_can_promote_after_passing_gates():
    registry = ResearchRegistry(PromotionPolicy(min_observations=10))
    registry.register(ResearchLane.FINRL, "allocation-policy-a", "commit-def")
    registry.record_metrics(
        ResearchLane.FINRL,
        "allocation-policy-a",
        ValidationMetrics(
            observations=50,
            net_return_pct=4.0,
            max_drawdown_pct=4.0,
            incremental_net_return_pct=1.2,
            average_slippage_bps=3.0,
            p95_latency_ms=100.0,
        ),
    )
    assert registry.eligible_for_paper(ResearchLane.FINRL, "allocation-policy-a")
    record = registry.promote_to_paper(ResearchLane.FINRL, "allocation-policy-a")
    assert record.status.value == "paper"
