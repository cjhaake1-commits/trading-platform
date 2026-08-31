from autotrader.strategy_health import assess_strategy_health, rank_opportunities


def test_small_sample_is_not_quarantined():
    result = assess_strategy_health("x", "v1", 2, -99)
    assert result["state"] == "INSUFFICIENT_SAMPLE"


def test_meaningful_negative_expectancy_is_quarantined():
    result = assess_strategy_health("x", "v1", 50, -1.0)
    assert result["state"] == "QUARANTINED"


def test_learning_changes_rank_but_risk_remains_authoritative():
    health = {
        ("good", "v1"): assess_strategy_health("good", "v1", 50, 1.0),
        ("bad", "v1"): assess_strategy_health("bad", "v1", 50, -1.0),
    }
    ranked = rank_opportunities([
        {"candidate_id": "good", "strategy": "good", "strategy_version": "v1", "raw_score": .70, "risk_approved": True},
        {"candidate_id": "bad", "strategy": "bad", "strategy_version": "v1", "raw_score": .75, "risk_approved": True},
    ], health)
    assert ranked[0]["candidate_id"] == "good"
    assert ranked[1]["execution_eligible"] is False
    assert ranked[1]["shadow_eligible"] is True


def test_risk_rejection_cannot_be_overridden_by_learning():
    health = {("good", "v1"): assess_strategy_health("good", "v1", 50, 1.0)}
    result = rank_opportunities([{"strategy": "good", "strategy_version": "v1", "raw_score": 1, "risk_approved": False}], health)[0]
    assert result["execution_eligible"] is False
