from autotrader.capital_recycling import evaluate_position, summarize_releases


def test_unknown_and_legacy_positions_are_protected():
    assert evaluate_position({"symbol": "GLD", "ownership": "UNKNOWN", "exit_signal": "STOP"}).action == "PROTECTED"
    assert evaluate_position({"symbol": "KX", "ownership": "LEGACY", "exit_signal": "STOP"}).action == "PROTECTED"


def test_explicit_owned_exit_releases_capital_without_submitting_order():
    decision = evaluate_position({"symbol": "SPY", "ownership": "PLATFORM_OWNED", "exit_signal": "TAKE_PROFIT", "market_value": 125, "realized_pnl": 4.5})
    summary = summarize_releases([decision])
    assert decision.action == "TAKE_PROFIT"
    assert summary["released_capital"] == 125
    assert summary["realized_pnl"] == 4.5
    assert summary["execution_side_effects"] == "NONE"
