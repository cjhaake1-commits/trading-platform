"""Fail-closed bridge from a qualified queue record to an existing paper adapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .forward_lifecycle import ForwardLifecycle


class PaperAdapter(Protocol):
    def submit(self, intent: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ExecutionGate:
    paper_mode: bool
    qualified_signal: bool
    risk_approved: bool
    capital_approved: bool
    provider_supported: bool
    session_allowed: bool
    ownership_allowed: bool

    @property
    def approved(self) -> bool:
        return all((self.paper_mode, self.qualified_signal, self.risk_approved,
                    self.capital_approved, self.provider_supported,
                    self.session_allowed, self.ownership_allowed))


def execute_qualified_queue_record(record: Mapping[str, object], *, adapter: PaperAdapter,
                                   lifecycle: ForwardLifecycle, now: str) -> dict[str, object]:
    """Submit only after every explicit safety gate passes."""
    gate = ExecutionGate(
        paper_mode=str(record.get("execution_mode", "")).upper() in {"PAPER", "PRACTICE", "SIM", "DEMO"},
        qualified_signal=bool(record.get("qualified_signal", False)),
        risk_approved=bool(record.get("risk_approved", False)),
        capital_approved=bool(record.get("capital_approved", False)),
        provider_supported=bool(record.get("provider_supported", False)),
        session_allowed=bool(record.get("session_allowed", False)),
        ownership_allowed=bool(record.get("ownership_allowed", False)),
    )
    result: dict[str, object] = {"submitted": False, "reason": "GATE_REJECTED", "side_effects": "NONE"}
    if not gate.approved:
        result["failed_gates"] = [name for name in ("paper_mode", "qualified_signal", "risk_approved", "capital_approved", "provider_supported", "session_allowed", "ownership_allowed") if not getattr(gate, name)]
        return result
    # Margin is an additional economic gate, never a source of capital.  A
    # provider's buying power is intentionally ignored here.
    margin_required = float(record.get("margin_required", 0) or 0)
    margin_available = float(record.get("margin_available", 0) or 0)
    if margin_required > margin_available:
        result["reason"] = "MARGIN_LIMIT"
        result["failed_gates"] = ["margin_available"]
        return result
    leverage = record.get("leverage_ratio")
    hard_limit = record.get("platform_margin_limit")
    if leverage is not None and hard_limit is not None and float(leverage) > float(hard_limit):
        result["reason"] = "LEVERAGE_LIMIT"
        result["failed_gates"] = ["platform_margin_limit"]
        return result
    trade_id = str(record.get("trade_id") or record.get("decision_id") or "")
    if not trade_id or str(record.get("ownership", "UNKNOWN")).upper() != "PLATFORM_OWNED":
        result["reason"] = "OWNERSHIP_REJECTED"
        return result
    lifecycle.record(trade_id=trade_id, stage="ORDER_INTENT", occurred_at=now,
                     pillar=str(record.get("pillar", "")), engine=str(record.get("engine", "")),
                     instrument=str(record.get("instrument", "")), payload={"ownership": "PLATFORM_OWNED", "intent": dict(record)})
    response = dict(adapter.submit(record))
    result.update(response)
    result["submitted"] = True
    result["side_effects"] = "PAPER_PROVIDER_ONLY"
    lifecycle.record(trade_id=trade_id, stage="ORDER", occurred_at=now,
                     pillar=str(record.get("pillar", "")), engine=str(record.get("engine", "")),
                     instrument=str(record.get("instrument", "")), payload={"ownership": "PLATFORM_OWNED", **response})
    return result
