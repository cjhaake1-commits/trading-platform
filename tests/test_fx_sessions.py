from autotrader.fx_signals import fx_session


def test_fx_session_uses_canonical_activity_labels():
    assert [fx_session(hour) for hour in (3, 8, 13, 18, 22)] == [
        "ASIA", "LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK", "OFF_PEAK"
    ]
