from autotrader.simulated_execution_test_mode import DiagnosticExecutionRecord, append_record, enabled


def test_diagnostic_mode_requires_simulation(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMULATED_EXECUTION_TEST_MODE", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("KALSHI_ENV", "demo")
    assert enabled()
    record = DiagnosticExecutionRecord("Stocks", "Alpaca PAPER", "SPY", "diagnostic")
    append_record(record, tmp_path / "diagnostic.json")
    assert '"DIAGNOSTIC_EXECUTION_TEST"' in (tmp_path / "diagnostic.json").read_text()


def test_diagnostic_mode_fails_closed_for_live(monkeypatch):
    monkeypatch.setenv("SIMULATED_EXECUTION_TEST_MODE", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    assert not enabled()
