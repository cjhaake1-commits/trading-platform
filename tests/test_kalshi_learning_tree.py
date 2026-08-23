from autotrader.kalshi.learning_tree import (
    CalibrationPoint,
    LeadLagPoint,
    build_learning_node,
    calibration_summary,
    candidate_feature_weight,
    cross_pillar_targets,
    lead_lag_summary,
)


def test_calibration_summary_uses_brier_score():
    summary = calibration_summary([
        CalibrationPoint(0.8, 1, "fed"),
        CalibrationPoint(0.2, 0, "fed"),
    ])
    assert summary.samples == 2
    assert round(summary.brier_score or 0, 4) == 0.04
    assert summary.calibration_gap == 0.0


def test_lead_lag_detects_directional_relationship():
    points = [
        LeadLagPoint(0.10, 0.02, 900, "Stocks", "SPY"),
        LeadLagPoint(0.08, 0.01, 900, "Stocks", "SPY"),
        LeadLagPoint(-0.10, -0.02, 900, "Stocks", "SPY"),
        LeadLagPoint(-0.08, -0.01, 900, "Stocks", "SPY"),
    ]
    summary = lead_lag_summary(points)
    assert summary.samples == 4
    assert summary.directional_hit_rate == 1.0
    assert summary.correlation is not None and summary.correlation > 0.9


def test_node_remains_zero_weight_even_when_shadow_candidate():
    points = [
        LeadLagPoint(0.10 if i % 2 == 0 else -0.10, 0.02 if i % 2 == 0 else -0.02, 300, "Forex", "EUR/USD")
        for i in range(30)
    ]
    node = build_learning_node(
        source_feature="kalshi.probability_change",
        pillar="Forex",
        symbol="EUR/USD",
        regime="risk_off",
        lead_lag=lead_lag_summary(points),
        calibration=calibration_summary([CalibrationPoint(0.7, 1)] * 20 + [CalibrationPoint(0.3, 0)] * 20),
    )
    assert node.evidence_state == "SHADOW_CANDIDATE"
    assert node.research_weight == 0.0
    assert node.broker_control is False
    assert 0.0 < candidate_feature_weight(node) <= 0.25


def test_cross_pillar_macro_mapping():
    targets = cross_pillar_targets("fed")
    assert set(targets) == {"Stocks", "Forex", "Metals/Commodities", "International", "Crypto"}


def test_non_kalshi_feature_cannot_build_node():
    try:
        build_learning_node(
            source_feature="external.signal",
            pillar="Stocks",
            symbol="SPY",
            regime="unknown",
            lead_lag=lead_lag_summary([]),
        )
    except ValueError as exc:
        assert "kalshi" in str(exc)
    else:
        raise AssertionError("non-Kalshi source feature should be rejected")
