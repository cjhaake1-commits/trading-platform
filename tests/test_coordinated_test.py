from autotrader.coordinated_test import (
    FIVE_PILLAR_BASELINE_VERSION,
    FivePillarTestConfig,
    five_pillar_performance,
)


def test_baseline_has_five_immutable_thousand_dollar_allocations():
    config = FivePillarTestConfig()
    assert config.baseline_version == FIVE_PILLAR_BASELINE_VERSION
    assert config.total_starting_capital == 5000.0
    assert set(config.allocations.values()) == {1000.0}
    assert len(config.allocations) == 5
    assert config.as_dict()["broker_excess_balance_deployable"] is False


def test_performance_tracks_cash_and_unrealized_separately_by_pillar():
    report = five_pillar_performance(
        completed_trades=[
            {"pillar": "alpaca_metals", "realized_pnl": 30.0, "fees_costs": 2.0},
            {"pillar": "alpaca_metals", "realized_pnl": -10.0, "fees_costs": 1.0},
        ],
        positions=[{"pillar": "alpaca_metals", "market_value": 200.0, "unrealized_pnl": 50.0}],
    )["Metals/Commodities"]
    assert report["net_generated_cash"] == 17.0
    assert report["unrealized_pnl"] == 50.0
    assert report["total_equity"] == 1067.0
    assert report["capital_deployed"] == 200.0
    assert report["number_of_trades"] == 2
    assert report["wins"] == 1 and report["losses"] == 1
