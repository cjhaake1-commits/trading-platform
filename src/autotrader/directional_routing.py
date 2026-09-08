"""Long/short candidate routing with explicit provider and risk gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class DirectionalDecision:
    direction: str
    state: str
    reason: str
    shortable: bool
    borrow_known: bool
    margin_required: float | None
    max_loss: float | None


def route_directional_candidate(candidate: Mapping[str, object], capability: Mapping[str, object]) -> dict[str, object]:
    direction = str(candidate.get("direction") or "UNKNOWN").upper()
    if direction not in {"LONG", "SHORT"}:
        return asdict(DirectionalDecision(direction, "REJECTED", "INVALID_DIRECTION", False, False, None, None))
    if direction == "LONG":
        return asdict(DirectionalDecision(direction, "ELIGIBLE", "LONG_PROVIDER_PATH", True, True, None, _number(candidate.get("max_loss"))))
    shortable = capability.get("short") is True or capability.get("short_supported") is True
    borrow_known = capability.get("borrow_available") is not None
    margin = _number(candidate.get("short_margin_required"))
    if not shortable:
        reason = str(capability.get("reason") or "SHORT_UNSUPPORTED")
        return asdict(DirectionalDecision(direction, "REJECTED", reason, False, borrow_known, margin, _number(candidate.get("max_loss"))))
    if capability.get("short_enabled") is not True:
        return asdict(DirectionalDecision(direction, "REJECTED", "SHORT_DISABLED_BY_PLATFORM_GOVERNANCE", True, borrow_known, margin, _number(candidate.get("max_loss"))))
    if capability.get("borrow_available") is not True:
        return asdict(DirectionalDecision(direction, "REJECTED", "BORROW_UNAVAILABLE_OR_UNKNOWN", True, borrow_known, margin, _number(candidate.get("max_loss"))))
    if margin is None or margin <= 0 or _number(candidate.get("max_loss")) is None:
        return asdict(DirectionalDecision(direction, "REJECTED", "SHORT_RISK_INPUT_INCOMPLETE", True, True, margin, _number(candidate.get("max_loss"))))
    return asdict(DirectionalDecision(direction, "ELIGIBLE", "SHORT_PROVIDER_PATH", True, True, margin, _number(candidate.get("max_loss"))))


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
