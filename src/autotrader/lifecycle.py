"""Functional lifecycle telemetry and stall classification."""

from __future__ import annotations

from datetime import UTC, datetime

STAGES = (
    "AUTH",
    "DISCOVERY",
    "MARKET_DATA",
    "NORMALIZATION",
    "FEATURES",
    "CANDIDATES",
    "SIGNAL",
    "STRATEGY_GOVERNANCE",
    "RISK",
    "ORDER",
    "FILL",
    "OWNERSHIP",
    "OUTCOME",
    "LEARNING",
)
LEGITIMATE = {"MARKET_CLOSED", "NO_SIGNAL", "SHADOW_ONLY", "ACTIVE_POSITION", "WORKING_ORDER"}


def classify_cycle(
    payload: dict[str, object], *, now: datetime | None = None, max_age_seconds: int = 900
) -> dict[str, object]:
    stage = str(payload.get("last_successful_lifecycle_stage") or payload.get("stage") or "UNKNOWN").upper()
    reason = str(payload.get("stop_reason") or payload.get("rejection") or payload.get("final_bottleneck") or "")
    if reason.upper() in LEGITIMATE or any(x in reason.upper() for x in LEGITIMATE):
        state = reason.upper() if reason.upper() in LEGITIMATE else "HEALTHY"
    elif stage == "UNKNOWN":
        state = "UNKNOWN"
    else:
        state = "HEALTHY"
    finished = payload.get("finished_at") or payload.get("timestamp")
    if finished:
        try:
            age = (
                (now or datetime.now(UTC)) - datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
            ).total_seconds()
            if age > max_age_seconds and state == "HEALTHY":
                state = "PIPELINE_STALL"
        except ValueError:
            state = "DEGRADED"
    return {
        "state": state,
        "stage": stage,
        "stop_reason": reason,
        "functional": state not in {"UNKNOWN", "PIPELINE_STALL", "DEGRADED"},
    }
