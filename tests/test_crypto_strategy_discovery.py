from datetime import UTC, datetime, timedelta

from autotrader.crypto_strategy_discovery import point_in_time_features, strategy_catalog
from autotrader.models import AssetClass, MarketBar


def test_point_in_time_features_do_not_read_future_bars():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [MarketBar("BTC/USD", AssetClass.CRYPTO, start + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
    before = point_in_time_features(bars, 5)
    after = point_in_time_features(bars[:6], 5)
    assert before == after


def test_catalog_contains_distinct_research_families():
    catalog = strategy_catalog()
    assert len(catalog) == 10
    assert len({candidate.family for candidate in catalog}) == 10
    assert "MEAN_REVERSION" in {candidate.family for candidate in catalog}
    assert "BREAKOUT_VOLATILITY_EXPANSION" in {candidate.family for candidate in catalog}
