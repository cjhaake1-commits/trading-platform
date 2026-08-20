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


def test_live_mode_requires_explicit_environment_unlock(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
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
