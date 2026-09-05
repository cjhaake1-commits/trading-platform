from autotrader.crypto_challenger_runtime import evaluate_challenger


def test_active_v2_remains_quarantined():
    result = evaluate_challenger(cohort="Active-V2", evidence={"sample_size": 100, "expectancy_after_costs": 1})
    assert result["state"] == "QUARANTINED"
    assert result["broker_submission"] is False


def test_new_positive_cohort_requires_sample_and_has_no_implicit_order():
    result = evaluate_challenger(cohort="challenger-1", evidence={"sample_size": 30, "expectancy_after_costs": .1})
    assert result["state"] == "PAPER_ELIGIBLE"
    assert result["broker_submission"] is False
