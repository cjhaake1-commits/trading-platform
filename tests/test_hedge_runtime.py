from autotrader.hedge_runtime import evaluate_hedge


def test_hedge_requires_downside_benefit_and_drawdown_reduction():
    candidate = evaluate_hedge(target_exposure="equity_beta", hedge_instrument="SPY", hedge_direction="SHORT", hedge_ratio=.2, capital_required=100, expected_cost=2, expected_downside_reduction=8, expected_return_impact=-1, expected_drawdown_impact=-6, basis_risk=.1)
    assert candidate.qualified is True


def test_random_opposite_position_is_not_a_hedge():
    candidate = evaluate_hedge(target_exposure="equity_beta", hedge_instrument="KALSHI", hedge_direction="SHORT", hedge_ratio=.2, capital_required=100, expected_cost=2, expected_downside_reduction=1, expected_return_impact=0, expected_drawdown_impact=1, basis_risk=1.2)
    assert candidate.qualified is False
