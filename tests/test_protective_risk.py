from datetime import UTC, datetime

from autotrader.models import AssetClass, PortfolioState, Position
from autotrader.protective_risk import DrawdownGovernor, ProtectiveRiskPolicy, StopManager


def test_drawdown_governor_trips_and_stays_latched():
    governor = DrawdownGovernor(
        1000.0,
        ProtectiveRiskPolicy(max_peak_drawdown_pct=0.08),
    )
    portfolio = PortfolioState(equity=919.0, cash=919.0)

    actions = governor.observe(portfolio)

    assert governor.kill_switch
    assert actions
    assert actions[0].kind == "kill_switch"

    portfolio.equity = 950.0
    actions = governor.observe(portfolio)
    assert actions
    assert governor.kill_switch


def test_stop_manager_never_loosen_stop_and_moves_to_break_even():
    position = Position(
        symbol="TEST",
        asset_class=AssetClass.STOCK,
        quantity=1.0,
        average_price=100.0,
        stop_price=98.0,
    )
    manager = StopManager(
        ProtectiveRiskPolicy(
            break_even_trigger_r=1.0,
            trailing_trigger_r=2.0,
            trailing_distance_r=1.0,
        )
    )
    manager.initialize(position, datetime(2026, 8, 16, tzinfo=UTC))

    assert manager.update_long(position, 101.0) is None
    action = manager.update_long(position, 102.0)
    assert action is not None
    assert position.stop_price == 100.0

    old_stop = position.stop_price
    manager.update_long(position, 101.5)
    assert position.stop_price >= old_stop


def test_stop_manager_trails_after_two_r():
    position = Position(
        symbol="TEST",
        asset_class=AssetClass.STOCK,
        quantity=1.0,
        average_price=100.0,
        stop_price=98.0,
    )
    manager = StopManager()

    action = manager.update_long(position, 105.0)

    assert action is not None
    assert position.stop_price >= 103.0
