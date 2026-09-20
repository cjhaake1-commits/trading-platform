"""Fail-closed bridge from a qualified queue record to an existing paper adapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .capital_reservations import CapitalReservations
from .forward_lifecycle import ForwardLifecycle
from .forward_verification import append_manifest, deterministic_submission_id


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
    amount = float(record.get("capital_required", 0) or 0)
    if amount <= 0:
        result["reason"] = "CAPITAL_RESERVATION_REQUIRED"
        return result
    epoch = __import__("autotrader.forward_verification", fromlist=["ensure_verification_epoch"]).ensure_verification_epoch()
    local_submission_id = deterministic_submission_id(
        experiment_id=str(record.get("experiment_id") or epoch["experiment_id"]),
        epoch_id=str(epoch["verification_epoch_id"]), pillar=str(record.get("pillar", "unknown")),
        strategy=str(record.get("strategy", record.get("engine", "unknown"))), intent_id=trade_id,
    )
    reservation_id = str(record.get("reservation_id") or f"res-{local_submission_id}")
    if not CapitalReservations().reserve(reservation_id=reservation_id, pillar=str(record.get("pillar", "UNKNOWN")), local_submission_id=local_submission_id, amount=amount, created_at=now):
        result["reason"] = "CAPITAL_RESERVATION_FAILED"
        return result
    manifest_record = {**dict(record), "local_submission_id": local_submission_id,
                      "reservation_id": reservation_id, "capital_reserved": amount,
                      "ownership_classification": "OWNERSHIP_PENDING",
                      "source": "execution_bridge", "timestamp": now}
    append_manifest("INTENT_CREATED", manifest_record)
    append_manifest("CAPITAL_RESERVED", manifest_record)
    lifecycle.record(trade_id=trade_id, stage="ORDER_INTENT", occurred_at=now,
                     pillar=str(record.get("pillar", "")), engine=str(record.get("engine", "")),
                     instrument=str(record.get("instrument", "")), payload={"ownership": "OWNERSHIP_PENDING", "intent": dict(record)})
    try:
        response = dict(adapter.submit(record))
    except (TimeoutError, OSError) as exc:
        append_manifest("UNKNOWN_PROVIDER_STATE", {**manifest_record, "source": type(exc).__name__})
        result["reason"] = "UNKNOWN_PROVIDER_STATE"
        result["provider_error"] = type(exc).__name__
        return result
    result.update(response)
    result["submitted"] = True
    result["side_effects"] = "PAPER_PROVIDER_ONLY"
    manifest_record = {**manifest_record, "provider_order_id": result.get("provider_order_id")}
    append_manifest("SUBMITTED", manifest_record)
    provider_state = str(result.get("status") or result.get("state") or "").upper()
    if provider_state in {"REJECTED", "CANCELED", "CANCELLED"}:
        append_manifest("REJECTED" if provider_state == "REJECTED" else "CANCELED", manifest_record)
    elif provider_state in {"ACKNOWLEDGED", "ACCEPTED"}:
        append_manifest("ACKNOWLEDGED", manifest_record)
    elif provider_state in {"WORKING", "OPEN", "NEW"}:
        append_manifest("WORKING", manifest_record)
    elif provider_state == "PARTIALLY_FILLED":
        append_manifest("PARTIAL_FILL", manifest_record)
    elif provider_state == "FILLED":
        append_manifest("FILLED", manifest_record)
    elif provider_state in {"TIMEOUT", "UNKNOWN", "UNKNOWN_PROVIDER_STATE"} or not provider_state:
        append_manifest("UNKNOWN_PROVIDER_STATE", manifest_record)
    lifecycle.record(trade_id=trade_id, stage="ORDER", occurred_at=now,
                     pillar=str(record.get("pillar", "")), engine=str(record.get("engine", "")),
                     instrument=str(record.get("instrument", "")), payload={"ownership": "OWNERSHIP_PENDING", **response})
    return result
