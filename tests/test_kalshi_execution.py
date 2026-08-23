from autotrader.kalshi.config import KalshiConfig
from autotrader.kalshi.execution import qualify_demo_order


def test_demo_execution_gate_requires_explicit_safe_configuration(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_DEMO_TRADING_ENABLED", "true")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    config = KalshiConfig.from_env()
    assert config.demo_trading_enabled is True
    decision = qualify_demo_order(config=config, market_open=True, fresh=True, valid_price=True,
                                 valid_tick=True, liquidity=True, spread_ok=True, fee_known=True,
                                 expected_edge=.02, capital_available=100, required_capital=10)
    assert decision.approved is True


def test_demo_execution_blocks_stale_or_negative_edge(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_TRADING_ENABLED", "true")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    config = KalshiConfig.from_env()
    decision = qualify_demo_order(config=config, market_open=True, fresh=False, valid_price=True,
                                 valid_tick=True, liquidity=True, spread_ok=True, fee_known=True,
                                 expected_edge=.02, capital_available=100, required_capital=10)
    assert decision.approved is False and decision.reason == "data stale"
