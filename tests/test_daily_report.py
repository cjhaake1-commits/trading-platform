from datetime import UTC, datetime

from autotrader.daily_report import write_report
from autotrader.paper_experiment import PaperExperimentLedger
from scripts.create_forward_campaign_checkpoint import build_checkpoint


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


def test_forward_checkpoint_does_not_misattributed_shared_cycles(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Stocks/Crypto", engine="autonomous-paper-trading", provider="paper",
        market="shared", strategy="cycle", strategy_version="v1", model_version="v1", timeframe="15m",
        features={}, candidate_status="CYCLE_COMPLETE", qualification_result="NO_TRADE",
    )
    checkpoint = build_checkpoint(str(tmp_path / "experiment.db"), datetime(2026, 8, 30, 1, tzinfo=UTC))
    assert checkpoint["engines"]["Stocks"]["cycles"] == "UNKNOWN"
    assert checkpoint["engines"]["Crypto"]["cycles"] == "UNKNOWN"
    assert checkpoint["engines"]["Crypto"]["shared_stocks_crypto_cycles"] == 1
