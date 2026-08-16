from autotrader.risk_profiles import competitive_paper_profile, conservative_baseline_profile


def test_competitive_profile_takes_more_risk_than_conservative_baseline():
    competitive = competitive_paper_profile()
    conservative = conservative_baseline_profile()

    assert competitive.risk_limits.risk_per_trade_pct > conservative.risk_limits.risk_per_trade_pct
    assert competitive.risk_limits.max_daily_loss_pct > conservative.risk_limits.max_daily_loss_pct
    assert competitive.risk_limits.max_peak_drawdown_pct > conservative.risk_limits.max_peak_drawdown_pct
    assert competitive.stack.max_portfolio_open_risk_pct > conservative.stack.max_portfolio_open_risk_pct
    assert competitive.correlation.max_bucket_notional_pct > conservative.correlation.max_bucket_notional_pct
    assert competitive.events.high_risk_scale > conservative.events.high_risk_scale


def test_operationally_dangerous_permissions_remain_off_in_both_profiles():
    for profile in (competitive_paper_profile(), conservative_baseline_profile()):
        assert not profile.risk_limits.allow_short_selling
        assert not profile.risk_limits.allow_leverage
