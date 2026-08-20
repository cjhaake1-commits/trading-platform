from __future__ import annotations

from collections.abc import Mapping


def runtime_status_labels(runtime: Mapping[str, object]) -> dict[str, str]:
    """Return independent, user-facing health and authorization labels."""

    healthy = runtime.get("healthy") is True
    autonomous_enabled = runtime.get("autonomous_enabled") is True
    execution_state = str(runtime.get("execution_state") or "faulted")
    if autonomous_enabled and healthy and execution_state == "armed_paper":
        autonomous_label = "ARMED (PAPER)"
    elif autonomous_enabled:
        autonomous_label = "BLOCKED (FAULT)"
    else:
        autonomous_label = "DISARMED"
    return {
        "runtime_health": "Healthy" if healthy else "Faulted",
        "autonomous_paper_trading": autonomous_label,
        "live_trading": "DISABLED",
    }
