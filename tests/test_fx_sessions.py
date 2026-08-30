from datetime import UTC, datetime, timedelta

from autotrader.fx_signals import _session_momentum, fx_session
from autotrader.models import AssetClass, Instrument, MarketBar, Side


def test_fx_session_uses_canonical_activity_labels():
    assert [fx_session(hour) for hour in (3, 8, 13, 18, 22)] == [
        "ASIA", "LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK", "OFF_PEAK"
    ]


def test_session_momentum_is_a_distinct_short_horizon_calculation():
    instrument = Instrument("EUR/USD", AssetClass.FOREX)
    bars = [
        MarketBar("EUR/USD", AssetClass.FOREX, datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i), close, close, close, close, 1)
        for i, close in enumerate((1.0, 1.01, 1.02, 1.03))
    ]
    proposal = _session_momentum(instrument, bars)
    assert proposal is not None
    assert proposal.source == "session_momentum"
    assert proposal.side is Side.BUY
