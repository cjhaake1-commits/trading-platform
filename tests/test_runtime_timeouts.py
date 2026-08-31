from datetime import UTC, datetime

from autotrader.audit import SQLiteAuditStore
from autotrader.runtime import AutonomousRuntime, JobResult, RunMode, RuntimeConfig


class SlowJob:
    name = "slow"
    cadence_seconds = 1

    def run(self, now):
        raise TimeoutError("provider timeout")


class FastJob:
    name = "fast"
    cadence_seconds = 1

    def run(self, now):
        return JobResult(True, "ok")


def test_timeout_result_isolated_and_following_job_runs(tmp_path):
    runtime = AutonomousRuntime(
        [SlowJob(), FastJob()], SQLiteAuditStore(str(tmp_path / "audit.db")),
        RuntimeConfig(mode=RunMode.PAPER, snapshot_path=tmp_path / "status.json", job_timeout_seconds=1),
        now_factory=lambda: datetime.now(UTC),
    )
    snapshot = runtime.run_once()
    assert snapshot["jobs"]["slow"]["last_error"] == "Job raised an exception"
    assert snapshot["jobs"]["fast"]["last_finished_at"] is not None
    assert runtime.states["slow"].last_error == "Job raised an exception"
