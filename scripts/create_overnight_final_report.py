#!/usr/bin/env python3
"""Create a truthful, durable overnight handoff from authoritative artifacts."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def _read(path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_report() -> str:
    forward = _read("var/reports/overnight-forward-campaign.json")
    progress = _read("var/reports/overnight-progress.json")
    daily = _read("var/reports/daily-learning-2026-08-30.json")
    master_checklist_available = Path("var/reports/master-70-item-checklist.json").exists()
    safety = forward.get("safety", {})
    runtime = forward.get("runtime_evidence", {})
    verified = (
        safety.get("live_trading_enabled") is False
        and safety.get("real_money_orders") == 0
        and runtime.get("unresolved_runtime_failures") == 0
        and bool(progress.get("runtime", {}).get("healthy"))
        and master_checklist_available
    )
    status = "HIGH_ACTIVITY_PAPER_LAB_V1 — VERIFIED" if verified else "HIGH_ACTIVITY_PAPER_LAB_V1 — NOT YET VERIFIED"
    lines = [status, "", f"Generated: {datetime.now(UTC).isoformat()}", f"Final verified SHA: {progress.get('git_sha', 'UNKNOWN')}", "", "## Runtime and safety", "", f"- LIVE_TRADING_ENABLED: {safety.get('live_trading_enabled', 'UNKNOWN')}", f"- Real-money orders: {safety.get('real_money_orders', 'UNKNOWN')}", f"- Runtime healthy: {progress.get('runtime', {}).get('healthy', 'UNKNOWN')}", f"- Unresolved runtime failures: {runtime.get('unresolved_runtime_failures', 'UNKNOWN')}", "", "## Forward campaign", ""]
    for name, values in (forward.get("engines") or {}).items():
        if isinstance(values, dict):
            lines.append(f"- {name}: health={values.get('activity_health', 'UNKNOWN')}, cycles={values.get('cycles', 'UNKNOWN')}, observations={values.get('observations', 'UNKNOWN')}")
    lines += ["", "## Performance", "", f"- Actual: {json.dumps(daily.get('actual_results', 'UNKNOWN'), sort_keys=True)}", f"- Shadow: {json.dumps(daily.get('shadow_scorecard', 'UNKNOWN'), sort_keys=True)}", "", "## Provider evidence", ""]
    for name, values in (forward.get("providers") or {}).items():
        if isinstance(values, dict):
            lines.append(f"- {name}: cycles={values.get('historical_cycle_count', 'UNKNOWN')}, health={values.get('activity_health', 'UNKNOWN')}, state={values.get('state', 'UNKNOWN')}")
    checklist_line = "- Master 70-item checklist: AVAILABLE" if master_checklist_available else "- Master 70-item checklist: NOT VERIFIED (authoritative master checklist is not present in the repository)."
    lines += ["", "## Acceptance status", "", checklist_line, "- Remaining requirements are not inferred from missing failures; each must be checked against its authoritative source.", "", "## Evidence limitations", "", "- Actual and shadow economics remain separate.", "- Calibrated edge and expected value remain UNKNOWN until independently calibrated.", "- Closed sessions and provider minimums are legitimate no-trade states.", "", "## Artifacts", "", "- overnight-forward-campaign.json", "- overnight-progress.json", "- overnight-errors.json", "- daily-learning-2026-08-30.json", ""]
    return "\n".join(lines)


def main() -> None:
    output = Path("var/reports/overnight-final.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
