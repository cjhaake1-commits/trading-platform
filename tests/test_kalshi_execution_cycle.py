from autotrader.kalshi.config import KalshiConfig


def test_kalshi_execution_config_is_immutable_no_trade():
    config = KalshiConfig()
    assert config.can_trade() is False
    assert config.broker_control is False
    assert config.paper_capital == 0
