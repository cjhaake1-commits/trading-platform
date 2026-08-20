from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Protocol

from .audit import SQLiteAuditStore
from .models import AuditEvent


class RunMode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(frozen=True)
class JobResult:
    ok: bool
    message: str
    data: dict[str, object] = field(default_factory=dict)


class RuntimeJob(Protocol):
    name: str
    cadence_seconds: float

    def run(self, now: datetime) -> JobResult: ...


@dataclass
class JobState:
    next_due_monotonic: float = 0.0
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_duration_ms: float | None = None
    consecutive_failures: int = 0
    disabled: bool = False
    last_error: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RunMode = RunMode.PAPER
    heartbeat_seconds: float = 1.0
    heartbeat_audit_seconds: float = 60.0
    max_consecutive_job_failures: int = 3
    snapshot_path: Path | None = None
    autonomous_enabled: bool = False


class AutonomousRuntime:
    """Long-running supervisor for market, research, learning, and execution jobs."""

    def __init__(
        self,
        jobs: list[RuntimeJob],
        audit: SQLiteAuditStore,
        config: RuntimeConfig | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.jobs = jobs
        self.audit = audit
        self.config = config or RuntimeConfig()
        self._monotonic = monotonic
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._states = {job.name: JobState() for job in jobs}
        if len(self._states) != len(jobs):
            raise ValueError("Runtime job names must be unique")
        self._started_at = self._now_factory()
        self._last_heartbeat_at: datetime | None = None
        self._last_heartbeat_audit_monotonic = 0.0
        self._validate_config()

    def _validate_config(self) -> None:
        if self.config.heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if self.config.heartbeat_audit_seconds <= 0:
            raise ValueError("heartbeat_audit_seconds must be positive")
        if self.config.max_consecutive_job_failures <= 0:
            raise ValueError("max_consecutive_job_failures must be positive")

        if self.config.mode is RunMode.LIVE:
            raise RuntimeError("Live runtime is disabled; only paper and shadow modes are available")
        if self.config.autonomous_enabled and self.config.mode is not RunMode.PAPER:
            raise RuntimeError("Autonomous execution authorization is valid only in paper mode")

    @property
    def states(self) -> dict[str, JobState]:
        return self._states

    def run_once(self) -> dict[str, object]:
        now = self._now_factory()
        mono_now = self._monotonic()
        self._last_heartbeat_at = now

        for job in self.jobs:
            state = self._states[job.name]
            if state.disabled or mono_now < state.next_due_monotonic:
                continue

            if job.cadence_seconds <= 0:
                raise ValueError(f"Job {job.name!r} cadence_seconds must be positive")

            state.last_started_at = now
            started = self._monotonic()
            try:
                result = job.run(now)
            except Exception as exc:
                result = JobResult(False, "Job raised an exception", {"error": str(exc)})

            finished = self._monotonic()
            duration_ms = max((finished - started) * 1000.0, 0.0)
            state.last_finished_at = self._now_factory()
            state.last_duration_ms = duration_ms
            state.next_due_monotonic = finished + job.cadence_seconds

            if result.ok:
                state.consecutive_failures = 0
                state.last_error = None
            else:
                state.consecutive_failures += 1
                state.last_error = result.message
                if state.consecutive_failures >= self.config.max_consecutive_job_failures:
                    state.disabled = True

            self.audit.append(
                AuditEvent(
                    event_type="runtime_job",
                    message=result.message,
                    data={
                        "job": job.name,
                        "ok": result.ok,
                        "mode": self.config.mode.value,
                        "duration_ms": duration_ms,
                        "consecutive_failures": state.consecutive_failures,
                        "disabled": state.disabled,
                        **result.data,
                    },
                )
            )

        if (
            mono_now - self._last_heartbeat_audit_monotonic
            >= self.config.heartbeat_audit_seconds
        ):
            self.audit.append(
                AuditEvent(
                    event_type="runtime_heartbeat",
                    message="Autonomous runtime heartbeat",
                    data={"mode": self.config.mode.value},
                )
            )
            self._last_heartbeat_audit_monotonic = mono_now

        snapshot = self.snapshot()
        self._write_snapshot(snapshot)
        return snapshot

    def run_forever(self, stop_event: Event | None = None) -> None:
        stop = stop_event or Event()
        self.audit.append(
            AuditEvent(
                event_type="runtime_started",
                message="Autonomous runtime started",
                data={"mode": self.config.mode.value, "jobs": [job.name for job in self.jobs]},
            )
        )
        try:
            while not stop.is_set():
                cycle_started = self._monotonic()
                self.run_once()
                elapsed = self._monotonic() - cycle_started
                wait_seconds = max(self.config.heartbeat_seconds - elapsed, 0.0)
                stop.wait(wait_seconds)
        finally:
            self.audit.append(
                AuditEvent(
                    event_type="runtime_stopped",
                    message="Autonomous runtime stopped",
                    data={"mode": self.config.mode.value},
                )
            )

    def enable_job(self, name: str) -> None:
        state = self._states[name]
        state.disabled = False
        state.consecutive_failures = 0
        state.last_error = None
        state.next_due_monotonic = 0.0

    def disable_job(self, name: str, reason: str = "Disabled by supervisor") -> None:
        state = self._states[name]
        state.disabled = True
        state.last_error = reason
        self.audit.append(
            AuditEvent(
                event_type="runtime_job_disabled",
                message=reason,
                data={"job": name, "mode": self.config.mode.value},
            )
        )

    def snapshot(self) -> dict[str, object]:
        healthy = self._operationally_healthy()
        if not healthy:
            execution_state = "faulted"
        elif self.config.autonomous_enabled:
            execution_state = "armed_paper"
        else:
            execution_state = "disarmed"
        return {
            "mode": self.config.mode.value,
            "healthy": healthy,
            "autonomous_enabled": self.config.autonomous_enabled,
            "execution_state": execution_state,
            "live_trading_enabled": False,
            "safety_configuration_valid": True,
            "started_at": self._started_at.isoformat(),
            "last_heartbeat_at": (
                None if self._last_heartbeat_at is None else self._last_heartbeat_at.isoformat()
            ),
            "jobs": {
                name: {
                    "disabled": state.disabled,
                    "consecutive_failures": state.consecutive_failures,
                    "last_error": state.last_error,
                    "last_started_at": (
                        None
                        if state.last_started_at is None
                        else state.last_started_at.isoformat()
                    ),
                    "last_finished_at": (
                        None
                        if state.last_finished_at is None
                        else state.last_finished_at.isoformat()
                    ),
                    "last_duration_ms": state.last_duration_ms,
                }
                for name, state in self._states.items()
            },
        }

    def _operationally_healthy(self) -> bool:
        if self._last_heartbeat_at is None:
            return False
        health = self._states.get("health")
        if health is not None and (
            health.disabled or health.consecutive_failures > 0 or health.last_error is not None
        ):
            return False
        if self.config.autonomous_enabled:
            for name in ("autonomous-paper-trading", "oanda-fx-paper-trading"):
                state = self._states.get(name)
                if state is not None and (
                    state.disabled or state.consecutive_failures > 0 or state.last_error is not None
                ):
                    return False
        return True

    def _write_snapshot(self, snapshot: dict[str, object]) -> None:
        path = self.config.snapshot_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
