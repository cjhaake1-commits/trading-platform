"""Sanitized, boundary-scoped runtime truth for external monitoring."""
from __future__ import annotations
import json, socket, subprocess, uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("var/runtime")
BOUNDARY = ROOT / "post_fix_boundary.json"
EVENTS = ROOT / "trade_lifecycle.jsonl"
STATUS = ROOT / "external_status.json"
STAGES = {"ORDER_SUBMITTED", "PROVIDER_ACK", "PARTIAL_FILL", "FILL", "POSITION_OPENED"}

def _now() -> str:
    return datetime.now(UTC).isoformat()

def _sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"

def ensure_boundary(*, runtime_instance_id: str | None = None) -> dict[str, object]:
    if BOUNDARY.exists():
        return json.loads(BOUNDARY.read_text(encoding="utf-8"))
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "boundary_id": str(uuid.uuid4()), "boundary_timestamp_utc": _now(),
        "git_commit_sha": _sha(), "git_branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
        "runtime_process_start_time": _now(), "hostname": socket.gethostname(),
        "environment": "PAPER/PRACTICE/SIM/DEMO", "live_trading_enabled": False,
        "runtime_instance_id": runtime_instance_id or str(uuid.uuid4()),
        "reason": "post-fix observability boundary",
    }
    BOUNDARY.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload

def _events(boundary: dict[str, object]) -> list[dict[str, object]]:
    if not EVENTS.exists():
        return []
    cutoff = str(boundary["boundary_timestamp_utc"])
    result = []
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            if str(event.get("event_time_utc", "")) > cutoff:
                result.append(event)
        except json.JSONDecodeError:
            continue
    return result

def record(event: dict[str, object], *, boundary: dict[str, object] | None = None) -> dict[str, object]:
    boundary = boundary or ensure_boundary()
    safe = {**event, "event_id": str(event.get("event_id") or uuid.uuid4()),
            "event_time_utc": str(event.get("event_time_utc") or _now()),
            "boundary_id": boundary["boundary_id"], "runtime_instance_id": boundary["runtime_instance_id"],
            "environment": "PAPER/PRACTICE/SIM/DEMO",
            "is_test_event": bool(event.get("is_test_event", False)),
            "is_replay": bool(event.get("is_replay", False)),
            "is_reconciliation": bool(event.get("is_reconciliation", False)),
            "is_historical": bool(event.get("is_historical", False)),
            "is_legacy": bool(event.get("is_legacy", False)),
            "is_protected_position": bool(event.get("is_protected_position", False))}
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, sort_keys=True, default=str) + "\n")
    return safe

def first_qualifying_trade() -> dict[str, object]:
    boundary = ensure_boundary()
    groups: dict[str, list[dict[str, object]]] = {}
    for event in _events(boundary):
        key = str(event.get("intent_id") or event.get("order_id") or event.get("candidate_id") or "")
        if key:
            groups.setdefault(key, []).append(event)
    for group in groups.values():
        for event in group:
            if event.get("event_type") in STAGES and not any(event.get(k) for k in (
                "is_test_event", "is_replay", "is_reconciliation", "is_historical",
                "is_legacy", "is_protected_position")):
                return {"qualified": True, **{k: event.get(k) for k in (
                    "boundary_id", "pillar", "instrument", "provider", "event_type",
                    "candidate_id", "intent_id", "order_id", "provider_order_id",
                    "allocated_capital", "notional", "platform_owned", "event_time_utc")},
                    "evidence": "var/runtime/trade_lifecycle.jsonl"}
    return {"qualified": False, "boundary_id": boundary["boundary_id"], "checked_at": _now(), "runtime_healthy": True}

def publish_status(status: dict[str, object] | None = None) -> dict[str, object]:
    boundary = ensure_boundary()
    result = {"generated_at_utc": _now(), "runtime_instance_id": boundary["runtime_instance_id"],
              "boundary": boundary, "git": {"commit_sha": _sha(), "branch": boundary.get("git_branch")},
              "environment": "PAPER/PRACTICE/SIM/DEMO", "live_trading_enabled": False,
              "runtime_health": (status or {}).get("healthy", True), "six_pillars": {},
              "first_qualifying_post_boundary_trade": first_qualifying_trade()}
    tmp = STATUS.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATUS)
    return result
