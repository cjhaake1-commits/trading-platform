from datetime import UTC, datetime

from autotrader.daily_report import write_report
from autotrader.paper_experiment import PaperExperimentLedger


def test_daily_report_is_dated_and_paper_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ledger = PaperExperimentLedger(tmp_path / "var/autotrader/paper_experiment.db")
    ledger.record_shadow_trade(
        shadow_id="S1", experiment_id="E1", pillar="Crypto", strategy_id="test", market="BTC/USD",
        direction="BUY", hypothetical_entry=100, entry_at="2026-08-30T00:00:00+00:00", entry_reason="test",
    )
    json_path, md_path = write_report(datetime(2026, 8, 30, 1, tzinfo=UTC), str(tmp_path / "var/autotrader/paper_experiment.db"))
    assert json_path.name == "daily-learning-2026-08-30.json"
    assert md_path.exists()
    assert '"live_trading_enabled": false' in json_path.read_text()
    assert '"real_money_orders": 0' in json_path.read_text()
