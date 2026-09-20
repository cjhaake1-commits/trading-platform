from datetime import UTC, datetime, timedelta

from autotrader.models import MarketBar
from autotrader.provider_scanners import scan_yahoo_universes


def test_scanner_emits_concrete_instruments_and_rejects_unknown_shorts():
    now = datetime(2026, 9, 16, tzinfo=UTC)
    def history(instrument, start, end, interval):
        return [MarketBar(instrument.symbol, instrument.asset_class, now - timedelta(hours=2), 100, 101, 99, 100, 1000), MarketBar(instrument.symbol, instrument.asset_class, now - timedelta(minutes=1), 100, 104, 99, 103, 1000)]
    rows, counts = scan_yahoo_universes(now=now, history=history)
    assert counts["stocks_scanned"] > 0
    assert all(row.instrument not in {"EQUITY_UNIVERSE", "LIQUID_FX_PAIRS"} for row in rows)
    assert any(row.instrument == "AAPL" and row.direction == "SHORT" and row.status == "ELIGIBLE" for row in rows)
