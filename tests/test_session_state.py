from datetime import UTC, datetime

from autotrader.session_state import session_state


def test_crypto_and_kalshi_are_continuous():
    assert session_state("Crypto").session == "CONTINUOUS"
    assert session_state("Kalshi").execution == "SCANNING"


def test_equity_closed_session_is_not_system_failure():
    state = session_state("Stocks / ETFs", datetime(2026, 8, 23, 12, tzinfo=UTC))
    assert state.state == "CLOSED"
    assert state.execution == "WAITING_FOR_SESSION"
