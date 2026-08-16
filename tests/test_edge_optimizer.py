from autotrader.edge_optimizer import EdgeAllocationPolicy, EdgeForecast, EdgeOptimizer


def test_positive_edge_is_ranked_and_bounded():
    optimizer = EdgeOptimizer(EdgeAllocationPolicy(max_growth_fraction=0.05))
    result = optimizer.evaluate(
        EdgeForecast(
            symbol="SPY",
            strategy_id="momentum",
            win_probability=0.60,
            average_win_bps=30.0,
            average_loss_bps=15.0,
            spread_bps=1.0,
            expected_slippage_bps=1.0,
            confidence=0.8,
        )
    )
    assert result.eligible
    assert 0 < result.growth_fraction <= 0.05
    assert result.priority_score > 0


def test_latency_can_destroy_short_lived_edge():
    optimizer = EdgeOptimizer()
    result = optimizer.evaluate(
        EdgeForecast(
            symbol="EUR/USD",
            strategy_id="fast_event",
            win_probability=0.65,
            average_win_bps=12.0,
            average_loss_bps=8.0,
            spread_bps=1.0,
            expected_slippage_bps=1.0,
            signal_half_life_ms=10.0,
            estimated_execution_latency_ms=100.0,
            confidence=0.9,
        )
    )
    assert not result.eligible
    assert "decays" in result.reason


def test_costs_can_eliminate_gross_edge():
    optimizer = EdgeOptimizer()
    result = optimizer.evaluate(
        EdgeForecast(
            symbol="QQQ",
            strategy_id="small_edge",
            win_probability=0.55,
            average_win_bps=10.0,
            average_loss_bps=8.0,
            spread_bps=3.0,
            expected_slippage_bps=3.0,
            explicit_cost_bps=1.0,
            confidence=0.9,
        )
    )
    assert not result.eligible
    assert "net edge" in result.reason
