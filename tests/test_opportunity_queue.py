from autotrader.opportunity_queue import Opportunity, margin_capability, rank_shadow_opportunities, shadow_allocation


def _op(**overrides):
    values = dict(
        pillar="Stocks", engine="paper", instrument="ABC", side="LONG",
        expected_return_after_costs=0.10, expected_loss=0.02,
        confidence=0.8, sample_quality=0.7, liquidity=0.9, correlation=0.2,
        holding_time_minutes=60, capital_required=100, margin_required=100,
        drawdown_contribution=0.02, strategy_version="test-v1",
        execution_mode="PAPER", eligible=True,
    )
    values.update(overrides)
    return Opportunity(**values)


def test_queue_ranks_only_known_eligible_opportunities():
    ranked = rank_shadow_opportunities([_op(instrument="BEST"), _op(instrument="UNKNOWN", confidence=None), _op(eligible=False)])
    assert [row["instrument"] for row in ranked] == ["BEST"]


def test_shadow_allocation_never_executes_or_changes_static_policy():
    ranked = rank_shadow_opportunities([_op(pillar="Crypto", instrument="BTC")])
    result = shadow_allocation({"Stocks": 1000, "Crypto": 1000}, ranked)
    assert result[0]["destination_pillar"] == "Crypto"
    assert result[0]["executed"] is False


def test_margin_fails_closed_without_platform_limit():
    result = margin_capability("Alpaca", supported=True, enabled=True, provider_limit=2.0, platform_limit=None, current_usage=0.0)
    assert result["margin_enabled"] is True
    assert result["fail_closed"] is True
