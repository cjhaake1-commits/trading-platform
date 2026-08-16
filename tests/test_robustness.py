from autotrader.robustness import RobustnessEvaluator, ScenarioResult


def test_robust_profile_passes_varied_positive_scenarios():
    result = RobustnessEvaluator().assess(
        [
            ScenarioResult("base", 18.0, 8.0, 200),
            ScenarioResult("higher_slippage", 12.0, 10.0, 200, slippage_bps=8.0),
            ScenarioResult("latency", 9.0, 11.0, 200, latency_ms=250.0),
            ScenarioResult("regime_shift", 4.0, 16.0, 150),
            ScenarioResult("adverse", -2.0, 20.0, 150),
        ]
    )
    assert result.passed
    assert result.positive_scenario_fraction == 0.8


def test_fragile_headline_return_is_rejected():
    result = RobustnessEvaluator().assess(
        [
            ScenarioResult("base", 30.0, 12.0, 100),
            ScenarioResult("higher_slippage", -8.0, 18.0, 100),
            ScenarioResult("latency", -10.0, 20.0, 100),
            ScenarioResult("regime_shift", -20.0, 30.0, 100),
        ]
    )
    assert not result.passed
    assert "enough scenarios" in result.reason or "drawdown" in result.reason
