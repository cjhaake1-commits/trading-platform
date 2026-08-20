from autotrader.cash_dashboard import aggregate_cash_dashboard


def test_realized_cash_excludes_unrealized_gains():
    metrics = aggregate_cash_dashboard(
        original_capital=4000.0,
        available_cash=3500.0,
        realized_records=[{"broker": "alpaca-paper", "realized_pnl": 100.0}],
        positions=[{"market_value": 500.0, "unrealized_pnl": 250.0}],
    )

    assert metrics.net_trading_cash_generated == 100.0
    assert metrics.unrealized_pnl == 250.0
    assert metrics.total_portfolio_equity == 4350.0
    assert metrics.generated_cash_ratio == 0.025
    assert metrics.realized_return == 0.025


def test_realized_cash_subtracts_losses_and_costs_by_pillar():
    metrics = aggregate_cash_dashboard(
        original_capital=4000.0,
        available_cash=3900.0,
        realized_records=[
            {"broker": "alpaca-paper", "realized_pnl": 50.0, "fees_costs": 5.0},
            {"broker": "oanda-practice", "realized_pnl": -20.0, "fees_costs": 2.0},
            {"broker": "saxo-sim", "realized_pnl": 10.0, "fees_costs": 1.0},
        ],
        positions=[],
    )

    assert metrics.net_trading_cash_generated == 32.0
    assert metrics.realized_pnl_by_pillar["Stocks"] == 45.0
    assert metrics.realized_pnl_by_pillar["Forex"] == -22.0
    assert metrics.realized_pnl_by_pillar["International"] == 9.0


def test_dashboard_separates_generated_cash_equity_and_internal_allocations():
    metrics = aggregate_cash_dashboard(
        original_capital=4000.0,
        available_cash=3000.0,
        protected_cash_reserve=400.0,
        broker_reported_virtual_equity=1_000_000.0,
        realized_records=[{"broker": "saxo-sim", "realized_pnl": 25.0}],
        positions=[{"market_value": 1000.0, "unrealized_pnl": 100.0}],
    ).as_dict()

    assert metrics["net_trading_cash_generated"] == 25.0
    assert metrics["total_portfolio_equity"] == 4125.0
    assert metrics["net_trading_cash_generated"] != metrics["total_portfolio_equity"]
    assert metrics["realized_return"] == metrics["generated_cash_ratio"]
    assert metrics["pillar_allocations"]["International"] == 1000.0
    assert metrics["broker_reported_virtual_equity"] == 1_000_000.0


def test_metals_realized_cash_excludes_unrealized_and_subtracts_costs():
    metrics = aggregate_cash_dashboard(
        original_capital=5000.0,
        available_cash=4800.0,
        realized_records=[
            {"broker": "alpaca-metals-paper", "pillar": "alpaca_metals", "realized_pnl": 30.0, "fees_costs": 2.0}
        ],
        positions=[{"pillar": "Metals/Commodities", "market_value": 200.0, "unrealized_pnl": 50.0}],
    )

    assert metrics.net_trading_cash_generated == 28.0
    assert metrics.realized_pnl_by_pillar["Metals/Commodities"] == 28.0
    assert metrics.unrealized_pnl == 50.0
    assert metrics.pillar_allocations["Metals/Commodities"] == 1000.0
    assert metrics.pillar_allocations["International"] == 1000.0
