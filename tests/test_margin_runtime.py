from autotrader.margin_runtime import calculate_margin


def test_margin_separates_economic_equity_and_notional():
    state = calculate_margin(economic_equity=1000, long_notional=500, short_notional=100, margin_used=100, platform_limit=2.0, enabled=False)
    assert state.gross_notional == 600
    assert state.net_notional == 400
    assert state.leverage_ratio == .6
    assert state.enabled is False


def test_margin_fails_closed_without_platform_limit():
    assert calculate_margin(economic_equity=1000, long_notional=500, short_notional=0, margin_used=0, platform_limit=None, enabled=True).enabled is False
