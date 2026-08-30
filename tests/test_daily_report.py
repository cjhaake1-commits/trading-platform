import json
import sqlite3
from datetime import UTC, datetime

from autotrader.daily_report import _evidence_classification, _strategy_classification, write_report
from autotrader.paper_experiment import PaperExperimentLedger
from scripts.create_daily_learning_report import write_report as write_legacy_report
from scripts.create_forward_campaign_checkpoint import _provider_health, build_checkpoint


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


def test_daily_report_includes_provider_performance_snapshots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/kalshi").mkdir(parents=True)
    (tmp_path / "var/kalshi/execution-predictions.json").write_text('{"state":"SCANNING","markets":7}')
    PaperExperimentLedger(tmp_path / "experiment.db")
    json_path, _ = write_report(datetime(2026, 8, 30, 1, tzinfo=UTC), str(tmp_path / "experiment.db"))
    report = __import__("json").loads(json_path.read_text())
    assert report["provider_performance"]["Kalshi Predictions"]["markets"] == 7
    assert report["provider_performance"]["Kalshi Perps"] == "UNKNOWN"


def test_daily_report_contains_descriptive_strategy_evidence(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Crypto", engine="crypto", provider="paper", market="BTC/USD",
        strategy="MOMENTUM", strategy_version="v1", model_version="v1", features={},
        candidate_status="SIGNAL", qualification_result="NO_TRADE", market_regime="TRENDING",
    )
    report = __import__("autotrader.daily_report", fromlist=["write_report"]).write_report(
        datetime(2026, 8, 30, 1, tzinfo=UTC), str(tmp_path / "experiment.db")
    )
    data = __import__("json").loads(report[0].read_text())
    assert data["strategy_evidence"]["MOMENTUM"]["signals"] == 1
    assert "does not imply governance promotion" in data["evidence_limitations"][-1]


def test_daily_report_classifies_legacy_and_infrastructure_strategies():
    assert _strategy_classification("crypto.momentum") == "CURRENT_MULTI_STRATEGY"
    assert _strategy_classification("autonomous:sma_cross") == "LEGACY_BASELINE"
    assert _strategy_classification("candidate_observation") == "INFRASTRUCTURE"
    assert _evidence_classification(10, 1.0) == "INSUFFICIENT_EVIDENCE"
    assert _evidence_classification(100, -1.0) == "EARLY_SIGNAL"


def test_legacy_daily_report_entrypoint_preserves_authoritative_schema(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    PaperExperimentLedger(tmp_path / "var/autotrader/paper_experiment.db")
    json_path, markdown_path = write_legacy_report(datetime(2026, 8, 30, 1, tzinfo=UTC))
    report = __import__("json").loads(json_path.read_text())
    assert "shadow_scorecard" in report
    assert "strategy_evidence" in report
    assert "## Actual paper results" in markdown_path.read_text()


def test_daily_report_keeps_runtime_provider_metrics_explicitly_proxied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    PaperExperimentLedger(tmp_path / "experiment.db")
    (tmp_path / "var/autotrader").mkdir(parents=True)
    with __import__("sqlite3").connect(tmp_path / "var/autotrader/audit.db") as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        connection.execute("INSERT INTO audit_events VALUES (1, 'runtime_job', 'ok', '{\"job\":\"oanda-fx-paper-trading\",\"ok\":true,\"duration_ms\":12}', '2026-08-30T00:00:00+00:00')")
    report = __import__("autotrader.daily_report", fromlist=["write_report"]).write_report(
        datetime(2026, 8, 30, 1, tzinfo=UTC), str(tmp_path / "experiment.db")
    )
    data = __import__("json").loads(report[0].read_text())
    assert data["provider_performance"]["OANDA"]["requests_job_proxy"] == 1
    assert data["provider_performance"]["OANDA"]["p95_latency_ms_job_proxy"] == 12.0


def test_daily_report_scorecard_uses_completed_shadow_outcomes_only(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_shadow_trade(
        shadow_id="S1", experiment_id="E1", pillar="Crypto", strategy_id="test", market="BTC/USD",
        direction="BUY", hypothetical_entry=100, entry_at="2026-08-30T00:00:00+00:00", entry_reason="test",
    )
    with __import__("sqlite3").connect(tmp_path / "experiment.db") as connection:
        connection.execute("UPDATE shadow_trades SET hypothetical_pnl=5, result='WIN', exit_at='2026-08-30T00:10:00+00:00', mfe=7, mae=-1 WHERE shadow_id='S1'")
    report = __import__("autotrader.daily_report", fromlist=["write_report"]).write_report(
        datetime(2026, 8, 30, 1, tzinfo=UTC), str(tmp_path / "experiment.db")
    )
    data = __import__("json").loads(report[0].read_text())
    assert data["shadow_scorecard"]["completed_experiments"] == 1
    assert data["shadow_scorecard"]["win_rate"] == 1.0
    assert data["shadow_scorecard"]["average_holding_seconds"] == 600.0
    assert data["shadow_by_pillar"]["Crypto"]["entries"] == 1
    assert data["shadow_by_pillar"]["Crypto"]["completed"] == 1
    assert data["shadow_by_strategy"]["test"]["hypothetical_expectancy"] == 5.0


def test_forward_checkpoint_does_not_misattributed_shared_cycles(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Stocks/Crypto", engine="autonomous-paper-trading", provider="paper",
        market="shared", strategy="cycle", strategy_version="v1", model_version="v1", timeframe="15m",
        features={}, candidate_status="CYCLE_COMPLETE", qualification_result="NO_TRADE",
    )
    checkpoint = build_checkpoint(str(tmp_path / "experiment.db"), datetime(2026, 8, 30, 1, tzinfo=UTC))
    assert checkpoint["engines"]["Stocks"]["cycles"] == "UNKNOWN"
    assert checkpoint["engines"]["Crypto"]["cycles"] == 1
    assert checkpoint["engines"]["Crypto"]["shared_stocks_crypto_cycles"] == 1
    assert checkpoint["engines"]["Crypto"]["activity_health_components"]["cycle"] is True
    assert checkpoint["engines"]["Crypto"]["activity_health"] == "UNKNOWN"


def test_forward_checkpoint_keeps_provider_history_unknown_when_only_snapshot_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/kalshi").mkdir(parents=True)
    (tmp_path / "var/kalshi/execution-predictions.json").write_text('{"observed_at":"now","markets":100}')
    checkpoint = build_checkpoint(str(tmp_path / "missing.db"), datetime(2026, 8, 30, 1, tzinfo=UTC))
    assert checkpoint["providers"]["Kalshi Predictions"]["scanned"] == 100
    assert checkpoint["providers"]["Kalshi Predictions"]["historical_cycle_count"] == "UNKNOWN"
    assert checkpoint["engines"]["Kalshi Predictions"]["cycles"] == "UNKNOWN"


def test_forward_checkpoint_exposes_provider_history_in_engine_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/kalshi").mkdir(parents=True)
    (tmp_path / "var/kalshi/execution-predictions.json").write_text(
        '{"observed_at":"now","markets":100,"cycle_count":12,"state":"SCANNING","funnel":{"data_valid":100}}'
    )
    checkpoint = build_checkpoint(str(tmp_path / "missing.db"), datetime(2026, 8, 30, 1, tzinfo=UTC))
    assert checkpoint["engines"]["Kalshi Predictions"]["cycles"] == 12
    assert checkpoint["engines"]["Kalshi Predictions"]["observations"] == 100
    assert checkpoint["engines"]["Kalshi Predictions"]["activity_health"] == 100


def test_provider_health_uses_only_observed_components():
    health, components = _provider_health({"observed_at": "now", "cycle_count": 3, "markets": 10, "funnel": {"data_valid": 10}})
    assert health == 100
    assert components["worker"] is True
    assert components["cycle"] is True


def test_forward_checkpoint_reports_runtime_successes_separately(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Stocks/Crypto", engine="autonomous-paper-trading", provider="paper",
        market="shared", strategy="cycle", strategy_version="v1", model_version="v1", timeframe="15m",
        features={}, candidate_status="CYCLE_COMPLETE", qualification_result="NO_TRADE",
    )
    audit = tmp_path / "audit.db"
    with __import__("sqlite3").connect(audit) as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        connection.execute("INSERT INTO audit_events VALUES (1, 'runtime_job', 'ok', '{\"job\":\"autonomous-paper-trading\",\"ok\":true}', '2026-08-30T00:00:00+00:00')")
        connection.execute("INSERT INTO audit_events VALUES (2, 'runtime_heartbeat', 'beat', '{}', '2026-08-30T00:01:00+00:00')")
    checkpoint = build_checkpoint(str(tmp_path / "experiment.db"), datetime(2026, 8, 30, 1, tzinfo=UTC), str(audit))
    assert checkpoint["engines"]["Crypto"]["cycles"] == 1
    assert checkpoint["runtime_evidence"]["successful_autonomous_cycles"] == 1
    assert checkpoint["runtime_evidence"]["consecutive_successful_autonomous_cycles"] == 1
    assert checkpoint["runtime_evidence"]["failed_runtime_jobs"] == 0
    assert checkpoint["runtime_evidence"]["resolved_runtime_failures"] == 0
    assert checkpoint["runtime_evidence"]["unresolved_runtime_failures"] == 0


def test_forward_checkpoint_counts_only_trailing_autonomous_successes(tmp_path):
    audit = tmp_path / "audit.db"
    with sqlite3.connect(audit) as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        for event_id, ok, minute in ((1, True, "00:00"), (2, False, "00:01"), (3, True, "00:02"), (4, True, "00:03")):
            connection.execute("INSERT INTO audit_events VALUES (?, 'runtime_job', 'cycle', ?, ?)", (event_id, json.dumps({"job": "autonomous-paper-trading", "ok": ok}), f"2026-08-30T{minute}:00+00:00"))
    checkpoint = build_checkpoint(str(tmp_path / "missing.db"), datetime(2026, 8, 30, 1, tzinfo=UTC), str(audit))
    assert checkpoint["runtime_evidence"]["autonomous_cycles"] == 4
    assert checkpoint["runtime_evidence"]["successful_autonomous_cycles"] == 3
    assert checkpoint["runtime_evidence"]["consecutive_successful_autonomous_cycles"] == 2


def test_forward_checkpoint_separates_recovered_runtime_failures(tmp_path):
    audit = tmp_path / "audit.db"
    with sqlite3.connect(audit) as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        connection.execute("INSERT INTO audit_events VALUES (1, 'runtime_job', 'failed', '{\"job\":\"worker\",\"ok\":false}', '2026-08-30T00:00:00+00:00')")
        connection.execute("INSERT INTO audit_events VALUES (2, 'runtime_job', 'success', '{\"job\":\"worker\",\"ok\":true}', '2026-08-30T00:01:00+00:00')")
    checkpoint = build_checkpoint(str(tmp_path / "missing.db"), datetime(2026, 8, 30, 1, tzinfo=UTC), str(audit))
    assert checkpoint["runtime_evidence"]["failed_runtime_jobs"] == 1
    assert checkpoint["runtime_evidence"]["resolved_runtime_failures"] == 1
    assert checkpoint["runtime_evidence"]["unresolved_runtime_failures"] == 0


def test_forward_checkpoint_survives_malformed_legacy_audit_data(tmp_path):
    audit = tmp_path / "audit.db"
    with __import__("sqlite3").connect(audit) as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        connection.execute("INSERT INTO audit_events VALUES (1, 'runtime_job', 'legacy', 'not-json', '2026-08-30T00:00:00+00:00')")
    checkpoint = build_checkpoint(str(tmp_path / "missing.db"), datetime(2026, 8, 30, 1, tzinfo=UTC), str(audit))
    assert checkpoint["runtime_evidence"]["malformed_audit_events"] == 1
