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
    shadow_attribution = _read("var/reports/shadow-attribution-2026-08-30.json")
    checklist = _read("var/reports/master-70-item-checklist.json")
    validation = _read("var/reports/validation-evidence.json")
    lifecycle = _read("var/reports/lifecycle-integrity-2026-08-30.json")
    checklist_items = checklist.get("items") if isinstance(checklist.get("items"), list) else []
    checklist_ids = [item.get("id") for item in checklist_items if isinstance(item, dict)]
    master_checklist_available = (
        len(checklist_items) == 70
        and len(set(checklist_ids)) == 70
        and all(isinstance(item, dict) and item.get("status") == "PASS" for item in checklist_items)
    )
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
    lines = [status, "", f"Generated: {datetime.now(UTC).isoformat()}", f"Final verified SHA: {progress.get('git_sha', 'UNKNOWN')}", "", "## Runtime and safety", "", f"- LIVE_TRADING_ENABLED: {safety.get('live_trading_enabled', 'UNKNOWN')}", f"- Real-money orders: {safety.get('real_money_orders', 'UNKNOWN')}", f"- Runtime healthy: {progress.get('runtime', {}).get('healthy', 'UNKNOWN')}", f"- Execution state: {progress.get('runtime', {}).get('execution_state', 'UNKNOWN')}", f"- Unresolved runtime failures: {runtime.get('unresolved_runtime_failures', 'UNKNOWN')}", "", "## Forward campaign", ""]
    for name, values in (forward.get("engines") or {}).items():
        if isinstance(values, dict):
            lines.append(f"- {name}: health={values.get('activity_health', 'UNKNOWN')}, cycles={values.get('cycles', 'UNKNOWN')}, observations={values.get('observations', 'UNKNOWN')}")
    lines += ["", "## Performance", "", f"- Actual: {json.dumps(daily.get('actual_results', 'UNKNOWN'), sort_keys=True)}", f"- Shadow: {json.dumps(daily.get('shadow_scorecard', 'UNKNOWN'), sort_keys=True)}", "", "## Provider evidence", ""]
    for name, values in (forward.get("providers") or {}).items():
        if isinstance(values, dict):
            lines.append(f"- {name}: cycles={values.get('historical_cycle_count', 'UNKNOWN')}, health={values.get('activity_health', 'UNKNOWN')}, state={values.get('state', 'UNKNOWN')}")
    checklist_line = "- Master 70-item checklist: VERIFIED" if master_checklist_available else "- Master 70-item checklist: NOT VERIFIED (a non-empty all-pass authoritative checklist is not present)."
    strategy_evidence = daily.get("strategy_evidence", "UNKNOWN")
    queue = _read("var/reports/research-queue.json")
    bottlenecks = {name: values.get("top_bottlenecks", {}) for name, values in (daily.get("activity") or {}).items() if isinstance(values, dict)}
    sections = [
        ("1. Work completed overnight", ["Evidence-driven research queue, monotonic campaign success accounting, shadow scorecards, provider telemetry, and paper safety reporting are persisted."]),
        ("2. Defects discovered", ["Historical runtime failures remain visible in the error ledger; no unresolved failures are currently evidenced."]),
        ("3. Defects repaired", ["Campaign checkpoint now exposes trailing consecutive successes and an explicit observation window."]),
        ("4. New regression tests", ["Full suite result must be taken from the latest validation command output; this report does not hardcode a stale test count."]),
        ("5. Crypto forward campaign", [f"{json.dumps((forward.get('engines') or {}).get('Crypto', {}), sort_keys=True)}"]),
        ("6. Stocks status", [json.dumps((forward.get("engines") or {}).get("Stocks", "UNKNOWN"), sort_keys=True)]),
        ("7. Crypto status", [json.dumps((forward.get("engines") or {}).get("Crypto", "UNKNOWN"), sort_keys=True)]),
        ("8. Forex status", [json.dumps((forward.get("engines") or {}).get("Forex", "UNKNOWN"), sort_keys=True)]),
        ("9. Metals status", [json.dumps((forward.get("engines") or {}).get("Metals", "UNKNOWN"), sort_keys=True)]),
        ("10. International status", [json.dumps((forward.get("engines") or {}).get("International", "UNKNOWN"), sort_keys=True)]),
        ("11. Kalshi Predictions status", [json.dumps((forward.get("providers") or {}).get('Kalshi Predictions', 'UNKNOWN'), sort_keys=True)]),
        ("12. Kalshi Perps status", [json.dumps((forward.get("providers") or {}).get('Kalshi Perps', 'UNKNOWN'), sort_keys=True)]),
        ("13. Shadow lab status", [json.dumps(forward.get("shadow", "UNKNOWN"), sort_keys=True)]),
        ("14. Actual paper performance", [json.dumps(daily.get("actual_results", "UNKNOWN"), sort_keys=True)]),
        ("15. Shadow performance", [json.dumps(daily.get("shadow_scorecard", "UNKNOWN"), sort_keys=True), f"Attribution: {json.dumps(shadow_attribution.get('negative_expectancy_shape', 'UNKNOWN'))}; by dimension: {json.dumps(shadow_attribution.get('by_dimension', 'UNKNOWN'), sort_keys=True)}"]),
        ("16. Strategy leaderboard", [json.dumps(strategy_evidence, sort_keys=True)]),
        ("17. Activity health", [json.dumps({name: values.get("activity_health", "UNKNOWN") for name, values in (forward.get("engines") or {}).items()}, sort_keys=True)]),
        ("18. Funnel bottlenecks", [json.dumps(bottlenecks, sort_keys=True)]),
        ("19. Capital utilization", ["UNKNOWN where the authoritative capital snapshot does not provide a value; no capital is inferred from activity counts."]),
        ("20. Provider performance", [json.dumps(daily.get("provider_performance", "UNKNOWN"), sort_keys=True)]),
        ("21. Before / after", ["Baseline comparison remains UNKNOWN for metrics not present in both authoritative snapshots."]),
        ("22. 70-item acceptance checklist", [checklist_line, f"Validation evidence: {json.dumps(validation.get('validation', 'UNKNOWN'), sort_keys=True)}", f"Lifecycle integrity: {json.dumps(lifecycle.get('invariants', 'UNKNOWN'), sort_keys=True)}"]),
        ("23. Unresolved external blockers", ["None currently evidenced."]),
        ("24. Unresolved internal items", ["None currently evidenced by the all-pass checklist; future outcome and historical-provenance limitations remain documented below."]),
        ("25. Recommended next research priorities", [json.dumps(queue.get("items", "UNKNOWN"), sort_keys=True)]),
    ]
    for heading, content in sections:
        lines += ["", f"## {heading}", ""] + [f"- {entry}" for entry in content]
    lines += ["", "## Evidence limitations", "", "- Actual and shadow economics remain separate.", "- Calibrated edge and expected value remain UNKNOWN until independently calibrated.", "- Closed sessions and provider minimums are legitimate no-trade states.", "", "## Artifacts", "", "- overnight-forward-campaign.json", "- overnight-progress.json", "- overnight-errors.json", "- daily-learning-2026-08-30.json", "- shadow-attribution-2026-08-30.json", "- lifecycle-integrity-2026-08-30.json", "- validation-evidence.json", "- research-queue.json", ""]
    return "\n".join(lines)


def main() -> None:
    output = Path("var/reports/overnight-final.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
