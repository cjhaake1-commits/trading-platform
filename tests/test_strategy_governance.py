from autotrader.strategy_governance import cohort_metrics


def test_insufficient_cohort_is_unproven():
    assert cohort_metrics([{"realized_pnl": 1}, {"realized_pnl": -1}])["label"] == "UNPROVEN"


def test_negative_cohort_is_not_promoted():
    result = cohort_metrics([{"realized_pnl": -1}] * 6)
    assert result["label"] == "NEGATIVE"
    assert result["expectancy_after_costs"] == -1
