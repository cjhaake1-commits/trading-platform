from __future__ import annotations

from dataclasses import dataclass, field

from .execution_safety import ExecutionReadiness, ExecutionReadinessGate
from .protective_risk import DrawdownGovernor, ProtectiveAction
from .reconciliation import ReconciliationResult


@dataclass(frozen=True)
class SafetySnapshot:
    execution_allowed: bool
    reason: str
    kill_switch: bool
    feed_ok: bool
    broker_ok: bool
    ledger_ok: bool
    reconciliation_ok: bool
    duplicate_ok: bool
    risk_ok: bool
    protective_actions: tuple[ProtectiveAction, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class SafetySupervisor:
    """Single fail-closed authority for creating new exposure.

    This class deliberately does not decide what to buy or sell. It combines
    health, persistence, reconciliation, idempotency, and hard-risk state into
    one execution permission consumed by the autonomous runtime.
    """

    def __init__(self, drawdown_governor: DrawdownGovernor) -> None:
        self.drawdown_governor = drawdown_governor

    def evaluate(
        self,
        *,
        feed_ok: bool,
        broker_ok: bool,
        ledger_ok: bool,
        reconciliation: ReconciliationResult,
        duplicate_ok: bool,
        risk_ok: bool,
        protective_actions: tuple[ProtectiveAction, ...] = (),
        metadata: dict[str, object] | None = None,
    ) -> SafetySnapshot:
        hard_risk_ok = risk_ok and not self.drawdown_governor.kill_switch
        readiness: ExecutionReadiness = ExecutionReadinessGate.evaluate(
            feed_ok=feed_ok,
            broker_ok=broker_ok,
            ledger_ok=ledger_ok and reconciliation.ok,
            risk_ok=hard_risk_ok,
            duplicate_ok=duplicate_ok,
        )
        if not reconciliation.ok:
            reason = reconciliation.reason
        elif self.drawdown_governor.kill_switch:
            reason = self.drawdown_governor.kill_reason or "risk kill switch active"
        else:
            reason = readiness.reason
        return SafetySnapshot(
            execution_allowed=readiness.ready,
            reason=reason,
            kill_switch=self.drawdown_governor.kill_switch,
            feed_ok=feed_ok,
            broker_ok=broker_ok,
            ledger_ok=ledger_ok,
            reconciliation_ok=reconciliation.ok,
            duplicate_ok=duplicate_ok,
            risk_ok=hard_risk_ok,
            protective_actions=protective_actions,
            metadata=metadata or {},
        )
