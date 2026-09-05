from autotrader.intraday_strategies import generate_candidate


def _features(**overrides):
    data = {"expected_return": .02, "expected_costs": .003, "expected_loss": .01, "confidence": .8, "liquidity": .9, "capital_required": 100, "expected_holding_minutes": 30, "direction": "LONG"}
    data.update(overrides); return data


def test_intraday_candidate_is_cost_aware_and_qualified():
    candidate = generate_candidate(pillar="stocks", instrument="SPY", strategy_id="MOMENTUM", features=_features())
    assert candidate.qualification_state == "QUALIFIED"
    assert candidate.expected_return_after_costs == .017


def test_negative_after_costs_is_persistable_rejection():
    candidate = generate_candidate(pillar="stocks", instrument="SPY", strategy_id="VWAP_RECLAIM", features=_features(expected_costs=.03))
    assert candidate.qualification_state == "REJECTED_NEGATIVE_EXPECTANCY"
