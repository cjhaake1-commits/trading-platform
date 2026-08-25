from autotrader.crypto_challenger_v2 import _metric, v2_decision


def test_v2_decision_is_cost_and_volatility_aware():
    config = {"net_edge_floor": 0.01, "spread_cap": 0.002, "volatility_cap": 0.02}
    assert v2_decision(challenger_accept=True, expected_net_edge=0.02, spread_cost=0.001, volatility=0.01, config=config) == "ACCEPT"
    assert v2_decision(challenger_accept=True, expected_net_edge=0.005, spread_cost=0.001, volatility=0.01, config=config) == "REJECT"
    assert v2_decision(challenger_accept=True, expected_net_edge=0.02, spread_cost=0.003, volatility=0.01, config=config) == "REJECT"


def test_metric_preserves_after_cost_drawdown_and_payoff_separation():
    result = _metric([2.0, -1.0, -3.0])
    assert result["sample"] == 3
    assert result["expectancy"] == -2 / 3
    assert result["max_drawdown"] == 4.0
    assert result["profit_factor"] == 0.5
