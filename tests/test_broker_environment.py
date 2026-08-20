import pytest

from autotrader.broker_environment import require_alpaca_paper_url, require_oanda_practice_url


def test_alpaca_live_host_is_rejected():
    with pytest.raises(RuntimeError, match="Alpaca PAPER"):
        require_alpaca_paper_url("https://api.alpaca.markets")


def test_oanda_live_host_is_rejected():
    with pytest.raises(RuntimeError, match="OANDA practice"):
        require_oanda_practice_url("https://api-fxtrade.oanda.com")


def test_exact_paper_and_practice_hosts_are_accepted():
    assert require_alpaca_paper_url("https://paper-api.alpaca.markets/") == "https://paper-api.alpaca.markets"
    assert require_oanda_practice_url("https://api-fxpractice.oanda.com") == "https://api-fxpractice.oanda.com"
