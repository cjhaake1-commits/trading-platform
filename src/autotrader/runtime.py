from __future__ import annotations

import json
import signal
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
from .paper_experiment import PaperExperimentLedger


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
    experiment_path: Path | None = None
    job_timeout_seconds: float = 90.0


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
        self._experiment_ledger = PaperExperimentLedger(self.config.experiment_path) if self.config.experiment_path else None
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
        # Publish heartbeat freshness before potentially slow provider/research
        # jobs run. The final snapshot below still captures their outcomes.
        self._write_snapshot(self.snapshot())

        for job in self.jobs:
            state = self._states[job.name]
            if state.disabled or mono_now < state.next_due_monotonic:
                continue

            if job.cadence_seconds <= 0:
                raise ValueError(f"Job {job.name!r} cadence_seconds must be positive")

            state.last_started_at = now
            started = self._monotonic()
            self._write_snapshot(self.snapshot())

            def _timeout(_signum, _frame):
                raise TimeoutError(f"job exceeded {self.config.job_timeout_seconds:.0f}s timeout")

            try:
                previous_handler = signal.signal(signal.SIGALRM, _timeout)
                signal.setitimer(signal.ITIMER_REAL, self.config.job_timeout_seconds)
                try:
                    result = job.run(now)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous_handler)
            except Exception as exc:
                result = JobResult(
                    False,
                    "Job raised an exception",
                    {"error": str(exc), "exception_type": type(exc).__name__, "exception_phase": "job.run",
                     "timeout": isinstance(exc, TimeoutError)},
                )

            finished = self._monotonic()
            duration_ms = max((finished - started) * 1000.0, 0.0)
            state.last_finished_at = self._now_factory()
            state.last_duration_ms = duration_ms
            state.next_due_monotonic = finished + job.cadence_seconds

            if self._experiment_ledger is not None:
                data = result.data
                rejection = data.get("rejection") or data.get("reason") or data.get("final_bottleneck")
                self._experiment_ledger.record_activity(
                    pillar=_pillar_for_job(job.name),
                    engine=job.name,
                    provider=_provider_for_job(job.name),
                    market=str(data.get("candidate") or data.get("symbol") or job.name),
                    strategy=str(data.get("strategy") or data.get("mode") or "cycle"),
                    strategy_version=str(data.get("strategy_version") or "runtime-v1"),
                    model_version="runtime-v1",
                    features={"job_result": data, "duration_ms": duration_ms},
                    candidate_status="CYCLE_COMPLETE",
                    qualification_result="QUALIFIED" if data.get("qualified") else "NO_TRADE",
                    rejection_reason=str(rejection) if rejection else None,
                    risk_decision=str(data.get("risk_approved")) if "risk_approved" in data else None,
                    order_id=str(data.get("order_id")) if data.get("order_id") else None,
                    provider_order_id=str(data.get("broker_order_id")) if data.get("broker_order_id") else None,
                    learning_update="cycle_persisted",
                )
                _record_candidate_payloads(self._experiment_ledger, job.name, data)

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
            # Make every transition visible even if a later provider job is
            # slow or unavailable; the next job still receives scheduler time.
            self._write_snapshot(self.snapshot())

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


def _pillar_for_job(name: str) -> str:
    mapping = {
        "autonomous-paper-trading": "Stocks/Crypto",
        "oanda-fx-paper-trading": "Forex",
        "alpaca-metals-paper-trading": "Metals",
        "saxo-international-paper-trading": "International",
        "kalshi-predictions": "Kalshi Predictions",
        "kalshi-perps": "Kalshi Perps",
    }
    return mapping.get(name, name)


def _provider_for_job(name: str) -> str:
    if name == "oanda-fx-paper-trading":
        return "OANDA Practice"
    if name == "saxo-international-paper-trading":
        return "Saxo SIM"
    if name.startswith("kalshi"):
        return "Kalshi Demo"
    return "Alpaca Paper"


def _record_candidate_payloads(ledger: PaperExperimentLedger, job_name: str, data: dict[str, object]) -> None:
    """Persist engine-produced candidate diagnostics at the shared runtime boundary."""
    payloads: list[dict[str, object]] = []
    for key in ("diagnostics", "fx_diagnostics", "ranked_candidates", "evaluations", "candidates"):
        value = data.get(key)
        if isinstance(value, list):
            payloads.extend(item for item in value if isinstance(item, dict))
    if not payloads:
        return
    pillar = _pillar_for_job(job_name)
    provider = _provider_for_job(job_name)
    for item in payloads:
        market = str(item.get("symbol") or item.get("market") or item.get("ticker") or job_name)
        rejection = item.get("rejection") or item.get("reason")
        qualified = bool(item.get("qualified"))
        ledger.record_activity(
            pillar=pillar,
            engine=job_name,
            provider=provider,
            market=market,
            asset_class="forex" if pillar == "Forex" else "stock",
            strategy_id=str(item.get("strategy") or "candidate_evaluation"),
            strategy=str(item.get("strategy") or "candidate_evaluation"),
            strategy_version="runtime-v1",
            model_version="runtime-v1",
            timeframe=str(item.get("timeframe") or "UNKNOWN"),
            market_regime=str(item.get("regime") or "UNKNOWN"),
            features=item,
            raw_score=float(item["score"]) if isinstance(item.get("score"), (int, float)) else None,
            normalized_confidence=float(item["confidence"]) if isinstance(item.get("confidence"), (int, float)) else None,
            candidate_status="QUALIFIED" if qualified else "CANDIDATE",
            qualification_result="QUALIFIED" if qualified else "REJECTED",
            rejection_reason=str(rejection) if rejection else None,
            risk_decision=str(item.get("risk_approved")) if "risk_approved" in item else None,
            learning_update="candidate_persisted",
        )
