import pytest

from autotrader.cash_engine import (
    OpportunityCandidate,
    capital_velocity_score,
    rank_opportunities,
    strategy_scorecard,
    validate_native_quote,
)


def test_velocity_and_risk_adjusted_ranking():
    assert capital_velocity_score(10, 100, 2) == 0.05
    fast = OpportunityCandidate("forex", "oanda-practice", "EUR_USD", "SHORT", "breakdown", .01, 10, 30, 100, 50, 20, .001, 1, .2, .8)
    slow = OpportunityCandidate("stocks", "alpaca-paper", "SPY", "LONG", "swing", .02, 20, 600, 100, 0, 20, .001, 1, .2, .8)
    assert rank_opportunities([slow, fast])[0]["instrument"] == "EUR_USD"


def test_scorecard_does_not_promote_small_sample():
    result = strategy_scorecard([{"realized_pnl": 5}, {"realized_pnl": -1}])
    assert result["classification"] == "EXPERIMENTAL"


def test_invalid_zero_ask_cannot_create_negative_spread():
    assert validate_native_quote(315.82, 0) == (False, None, "INVALID_QUOTE")
    valid, spread, error = validate_native_quote(705.09, 705.16)
    assert valid and error is None and spread == pytest.approx(0.07)
