from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar, Side, TradeProposal
from autotrader.risk import RiskEngine
from autotrader.simulator import SimulationConfig, WalkForwardSimulator


def make_bars(closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MarketBar(
            symbol="TEST",
            asset_class=AssetClass.STOCK,
            timestamp=start + timedelta(days=i),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1000.0,
        )
        for i, close in enumerate(closes)
    ]


def one_time_buy():
    fired = False

    def strategy(instrument, bars):
        nonlocal fired
        if fired:
            return None
        fired = True
        price = bars[-1].close
        return TradeProposal(
            symbol=instrument.symbol,
            asset_class=instrument.asset_class,
            side=Side.BUY,
            entry_price=price,
            stop_price=price * 0.95,
            confidence=0.5,
            source="test",
        )

    return strategy


def test_walk_forward_executes_signal_on_next_bar():
    bars = make_bars([100, 101, 102, 103, 104, 105])
    simulator = WalkForwardSimulator(
        RiskEngine(),
        SimulationConfig(commission_pct=0.0, slippage_pct=0.0),
    )
    result = simulator.run(
        Instrument("TEST", AssetClass.STOCK),
        bars,
        one_time_buy(),
        warmup_bars=2,
    )

    assert result.fills
    assert result.fills[0].side is Side.BUY
    # Signal appears after bar index 2 and must execute at index 3 open.
    assert result.fills[0].bar_index == 3
    assert result.metrics is not None
