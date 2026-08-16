from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar, Side
from autotrader.strategies import BaselineStrategies, StrategyConfig


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


def test_sma_cross_emits_buy_for_uptrend():
    strategy = BaselineStrategies(StrategyConfig(fast_window=3, slow_window=5))
    proposal = strategy.sma_cross(
        Instrument("TEST", AssetClass.STOCK),
        make_bars([100, 101, 102, 104, 106]),
    )
    assert proposal is not None
    assert proposal.side is Side.BUY
    assert proposal.stop_price < proposal.entry_price


def test_breakout_detects_new_high():
    strategy = BaselineStrategies(StrategyConfig(breakout_window=3))
    proposal = strategy.breakout(
        Instrument("TEST", AssetClass.STOCK),
        make_bars([100, 101, 102, 105]),
    )
    assert proposal is not None
    assert proposal.side is Side.BUY


def test_mean_reversion_detects_large_drop():
    strategy = BaselineStrategies(StrategyConfig(zscore_window=5, zscore_entry=1.0))
    proposal = strategy.mean_reversion(
        Instrument("TEST", AssetClass.STOCK),
        make_bars([100, 100, 100, 100, 90]),
    )
    assert proposal is not None
    assert proposal.side is Side.BUY
