from datetime import UTC, datetime

from autotrader.session_state import fx_is_open, international_venue_state, metals_session_state, session_state


def test_crypto_and_kalshi_are_continuous():
    assert session_state("Crypto").session == "CONTINUOUS"
    assert session_state("Kalshi").execution == "SCANNING"


def test_equity_closed_session_is_not_system_failure():
    state = session_state("Stocks / ETFs", datetime(2026, 8, 23, 12, tzinfo=UTC))
    assert state.state == "CLOSED"
    assert state.execution == "WAITING_FOR_SESSION"


def test_fx_global_week_reopen_and_close():
    assert fx_is_open(datetime(2026, 8, 23, 20, 0, tzinfo=UTC)) is False
    assert fx_is_open(datetime(2026, 8, 23, 21, 0, tzinfo=UTC)) is True
    assert fx_is_open(datetime(2026, 8, 24, 12, tzinfo=UTC)) is True
    assert fx_is_open(datetime(2026, 8, 21, 20, 59, tzinfo=UTC)) is True
    assert fx_is_open(datetime(2026, 8, 21, 21, 1, tzinfo=UTC)) is False
    assert fx_is_open(datetime(2026, 8, 22, 12, tzinfo=UTC)) is False


def test_international_and_metals_are_venue_specific():
    moment = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    asia = international_venue_state("asia", moment)
    europe = international_venue_state("europe", moment)
    assert asia.venue == "asia" and europe.venue == "europe"
    assert asia.state != europe.state or asia.session != europe.session
    metals = metals_session_state("XAU/USD", moment, venue="oanda")
    assert metals.session == "OANDA_METALS"
