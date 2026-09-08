from autotrader.intraday_strategies import generate_candidate


def _features(**overrides):
    data = {
        "expected_return": 0.02,
        "expected_costs": 0.003,
        "expected_loss": 0.01,
        "confidence": 0.8,
        "liquidity": 0.9,
        "capital_required": 100,
        "expected_holding_minutes": 30,
        "direction": "LONG",
    }
    data.update(overrides)
    return data


def test_intraday_candidate_is_cost_aware_and_qualified():
    candidate = generate_candidate(pillar="stocks", instrument="SPY", strategy_id="MOMENTUM", features=_features())
    assert candidate.qualification_state == "QUALIFIED"
    assert candidate.expected_return_after_costs == 0.017


def test_negative_after_costs_is_persistable_rejection():
    candidate = generate_candidate(
        pillar="stocks", instrument="SPY", strategy_id="VWAP_RECLAIM", features=_features(expected_costs=0.03)
    )
    assert candidate.qualification_state == "REJECTED_NEGATIVE_EXPECTANCY"
