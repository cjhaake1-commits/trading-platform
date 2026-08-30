from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

import autotrader.runtime_app as runtime_app_module
from autotrader.audit import SQLiteAuditStore
from autotrader.runtime import AutonomousRuntime, JobResult, RunMode, RuntimeConfig


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@dataclass
class CountingJob:
    name: str = "scanner"
    cadence_seconds: float = 5.0
    calls: int = 0
    fail: bool = False

    def run(self, now: datetime) -> JobResult:
        self.calls += 1
        if self.fail:
            return JobResult(False, "failed")
        return JobResult(True, "ok", {"calls": self.calls})


def fixed_now() -> datetime:
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def test_runtime_persists_candidate_payloads_separately_from_cycle(tmp_path):
    ledger_path = tmp_path / "experiments.db"
    runtime = AutonomousRuntime(
        [CountingJob(name="oanda-fx-paper-trading")],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(experiment_path=ledger_path, heartbeat_audit_seconds=60.0),
        now_factory=fixed_now,
    )
    runtime.jobs[0].run = lambda now: JobResult(True, "ok", {"fx_diagnostics": [{"symbol": "EUR_USD", "score": 0.7, "qualified": False, "reason": "spread"}]})
    runtime.run_once()
    with __import__("sqlite3").connect(ledger_path) as connection:
        row = connection.execute("SELECT pillar,market,candidate_status,rejection_reason FROM activity_observations WHERE market='EUR_USD'").fetchone()
    assert row == ("Forex", "EUR_USD", "CANDIDATE", "spread")


def test_runtime_respects_job_cadence(tmp_path):
    clock = FakeClock()
    job = CountingJob()
    runtime = AutonomousRuntime(
        [job],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(heartbeat_audit_seconds=60.0),
        monotonic=clock.monotonic,
        now_factory=fixed_now,
    )

    runtime.run_once()
    runtime.run_once()
    assert job.calls == 1

    clock.advance(5.0)
    runtime.run_once()
    assert job.calls == 2


def test_runtime_disables_repeatedly_failing_job(tmp_path):
    clock = FakeClock()
    job = CountingJob(fail=True, cadence_seconds=1.0)
    runtime = AutonomousRuntime(
        [job],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(max_consecutive_job_failures=2, heartbeat_audit_seconds=60.0),
        monotonic=clock.monotonic,
        now_factory=fixed_now,
    )

    runtime.run_once()
    clock.advance(1.0)
    runtime.run_once()

    assert runtime.states[job.name].disabled
    assert runtime.states[job.name].consecutive_failures == 2


def test_live_mode_remains_unavailable_even_with_environment_unlock(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    with pytest.raises(RuntimeError, match="Live runtime is disabled"):
        AutonomousRuntime(
            [CountingJob()],
            SQLiteAuditStore(tmp_path / "audit.db"),
            RuntimeConfig(mode=RunMode.LIVE),
            now_factory=fixed_now,
        )


def test_runtime_writes_atomic_status_snapshot(tmp_path):
    snapshot = tmp_path / "status.json"
    runtime = AutonomousRuntime(
        [CountingJob()],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(snapshot_path=snapshot, heartbeat_audit_seconds=60.0),
        now_factory=fixed_now,
    )

    state = runtime.run_once()

    assert snapshot.exists()
    assert state["mode"] == "paper"
    assert "scanner" in state["jobs"]
    assert state["healthy"] is True
    assert state["autonomous_enabled"] is False
    assert state["execution_state"] == "disarmed"
    assert state["live_trading_enabled"] is False


def test_runtime_is_healthy_when_paper_execution_is_armed(tmp_path):
    runtime = AutonomousRuntime(
        [
            CountingJob(name="health"),
            CountingJob(name="autonomous-paper-trading"),
            CountingJob(name="oanda-fx-paper-trading"),
        ],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(autonomous_enabled=True, heartbeat_audit_seconds=60.0),
        now_factory=fixed_now,
    )

    state = runtime.run_once()

    assert state["healthy"] is True
    assert state["autonomous_enabled"] is True
    assert state["execution_state"] == "armed_paper"


def test_unhealthy_disarmed_runtime_is_faulted_without_authorization(tmp_path):
    runtime = AutonomousRuntime(
        [CountingJob(name="health", fail=True)],
        SQLiteAuditStore(tmp_path / "audit.db"),
        RuntimeConfig(autonomous_enabled=False, heartbeat_audit_seconds=60.0),
        now_factory=fixed_now,
    )

    state = runtime.run_once()

    assert state["healthy"] is False
    assert state["autonomous_enabled"] is False
    assert state["execution_state"] == "faulted"


def test_autonomous_arming_defaults_false_and_requires_exact_true(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_TRADING_ENABLED", raising=False)
    assert not runtime_app_module.autonomous_trading_armed()
    monkeypatch.setenv("AUTONOMOUS_TRADING_ENABLED", "yes")
    assert not runtime_app_module.autonomous_trading_armed()
    monkeypatch.setenv("AUTONOMOUS_TRADING_ENABLED", "true")
    assert runtime_app_module.autonomous_trading_armed()


def test_runtime_restart_with_autonomous_flag_remains_disarmed_by_default(
    tmp_path, monkeypatch
):
    captured = {}
    monkeypatch.delenv("AUTONOMOUS_TRADING_ENABLED", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "autotrader-runtime",
            "--autonomous-paper",
            "--audit-db",
            str(tmp_path / "audit.db"),
            "--status",
            str(tmp_path / "status.json"),
            "--ledger",
            str(tmp_path / "portfolio.db"),
            "--idempotency",
            str(tmp_path / "idempotency.db"),
        ],
    )

    def capture_without_starting(self, stop_event=None):
        captured.update(self.snapshot())

    monkeypatch.setattr(AutonomousRuntime, "run_forever", capture_without_starting)
    runtime_app_module.main()

    assert captured["mode"] == "paper"
    assert captured["jobs"]["autonomous-paper-trading"]["disabled"]
    assert captured["jobs"]["oanda-fx-paper-trading"]["disabled"]
    assert (
        "AUTONOMOUS_TRADING_ENABLED"
        in captured["jobs"]["autonomous-paper-trading"]["last_error"]
    )


def test_runtime_includes_all_five_pillar_jobs_when_autonomous_paper_requested(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setenv("AUTONOMOUS_TRADING_ENABLED", "false")
    monkeypatch.setattr(
        "sys.argv",
        [
            "autotrader-runtime",
            "--autonomous-paper",
            "--audit-db",
            str(tmp_path / "audit.db"),
            "--status",
            str(tmp_path / "status.json"),
            "--ledger",
            str(tmp_path / "portfolio.db"),
            "--idempotency",
            str(tmp_path / "idempotency.db"),
        ],
    )

    def capture_without_starting(self, stop_event=None):
        captured.update(self.snapshot())

    monkeypatch.setattr(AutonomousRuntime, "run_forever", capture_without_starting)
    runtime_app_module.main()

    assert captured["jobs"]["autonomous-paper-trading"]["disabled"]
    assert captured["jobs"]["oanda-fx-paper-trading"]["disabled"]
    assert captured["jobs"]["alpaca-metals-paper-trading"]["disabled"]
    assert captured["jobs"]["saxo-international-paper-trading"]["disabled"]
