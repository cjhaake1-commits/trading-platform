#!/usr/bin/env python3
"""Materialize the authoritative, conservative 70-item lab acceptance checklist."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ITEMS = [
    ("A", "Runtime healthy"), ("B", "Final observation window has no deterministic failures"),
    ("C", "Crypto multi-strategy evaluator operational"), ("D", "Strategy aliasing eliminated or unavailable is explicit"),
    ("E", "Stable parent experiment lifecycle operational"), ("F", "Confluence ties are explicit and safe"),
    ("G", "HOLD shadow positions are prohibited"), ("H", "Shadow entry is operational"),
    ("I", "Shadow exit is operational"), ("J", "Actual and shadow economics are isolated"),
    ("K", "Kalshi Predictions candidate telemetry operational"), ("L", "Kalshi Perps candidate telemetry operational"),
    ("M", "Available engines produce fresh decision observations"), ("N", "Activity health is operational"),
    ("O", "Funnel analytics are operational"), ("P", "Bottleneck profiler is operational"),
    ("Q", "Scorecards use completed outcomes"), ("R", "Provider metrics are operational"),
    ("S", "Dashboard integrates lab telemetry"), ("T", "Daily learning report is generated"),
    ("U", "Crypto campaign has at least 10 successful fresh cycles"), ("V", "Full test suite passes"),
    ("W", "Ruff passes"), ("X", "Compilation passes"), ("Y", "Diff check passes"),
    ("Z", "VM, GitHub, and deployed state reconcile"), ("AA", "Runtime process topology is singular"),
    ("AB", "Streamlit is healthy"), ("AC", "Dashboard HTTP status is 200"),
    ("AD", "LIVE_TRADING_ENABLED is false"), ("AE", "Real-money order count is zero"),
    ("1", "Parent experiment identity is stable across lifecycle events"), ("2", "Lifecycle events have distinct event identity"),
    ("3", "Multiple strategy evaluations share the economic parent"), ("4", "Shadow lifecycle retains the economic parent"),
    ("5", "Actual order lifecycle retains the economic parent"), ("6", "Momentum uses return or rate-of-change features"),
    ("7", "Breakout uses a rolling range"), ("8", "Mean reversion uses normalized deviation"),
    ("9", "Trend following uses moving-average structure or slope"), ("10", "Relative strength refuses unsupported benchmarks"),
    ("11", "Strategy outputs include version and timeframe"), ("12", "Strategy outputs include data quality and rejection reason"),
    ("13", "Edge proxy is distinct from calibrated estimated edge"), ("14", "Expected value remains unknown until calibrated"),
    ("15", "Confluence persists vote counts"), ("16", "Confluence persists confidence and dispersion"),
    ("17", "Confluence conflict state is explicit"), ("18", "Confluence tie behavior is deterministic"),
    ("19", "One confluence produces one portfolio decision"), ("20", "Counterfactual no-trade is persisted"),
    ("21", "Shadow entries use forward observations"), ("22", "Shadow exits persist reasons"),
    ("23", "Shadow MFE and MAE are persisted"), ("24", "Near-threshold distance is persisted"),
    ("25", "Accepted and near-threshold populations remain separate"), ("26", "Kalshi uses event-market semantics"),
    ("27", "Kalshi unknown model probability is not invented"), ("28", "Kalshi liquidity gates remain conservative"),
    ("29", "Kalshi directional semantics remain provider-native"), ("30", "Legacy Kalshi exposure remains segregated"),
    ("31", "Legacy Saxo exposure remains segregated"), ("32", "Legacy stock exposure remains segregated"),
    ("33", "Current-fund ownership is explicit"), ("34", "International provider identity is Saxo SIM"),
    ("35", "International session state is venue-aware"), ("36", "Closed venues produce SESSION_BLOCKED"),
    ("37", "Next-open readiness is persisted"), ("38", "Portfolio risk checks same-instrument exposure"),
    ("39", "Portfolio risk checks cross-pillar correlation"),
]


def _status(item_id: str, safety: dict[str, object], runtime: dict[str, object], progress: dict[str, object]) -> tuple[str, str]:
    if item_id in {"AD", "67"}:
        return ("PASS", "paper safety verifier reports live trading disabled") if safety.get("live_trading_enabled") is False else ("FAIL", "live trading safety evidence is not false")
    if item_id == "AE":
        return ("PASS", "paper safety verifier reports zero real-money orders") if safety.get("real_money_orders") == 0 else ("FAIL", "real-money order evidence is nonzero")
    if item_id in {"A", "B"}:
        return ("PASS", "forward campaign runtime evidence") if runtime.get("unresolved_runtime_failures") == 0 and progress.get("runtime", {}).get("healthy") else ("UNKNOWN", "runtime evidence is incomplete")
    if item_id in {"AB", "AC"}:
        return ("PASS", "current progress checkpoint") if progress.get("runtime", {}).get("streamlit_http") == 200 else ("UNKNOWN", "HTTP evidence is not in checkpoint")
    return ("UNKNOWN", "requires authoritative requirement-specific evidence")


def build_checklist() -> dict[str, object]:
    def read(path: str) -> dict[str, object]:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    forward = read("var/reports/overnight-forward-campaign.json")
    progress = read("var/reports/overnight-progress.json")
    safety = forward.get("safety", {}) if isinstance(forward.get("safety"), dict) else {}
    runtime = forward.get("runtime_evidence", {}) if isinstance(forward.get("runtime_evidence"), dict) else {}
    items = [{"id": item_id, "requirement": text, "status": _status(item_id, safety, runtime, progress)[0], "basis": _status(item_id, safety, runtime, progress)[1]} for item_id, text in ITEMS]
    return {"report_id": "MASTER_70_ITEM_ACCEPTANCE", "generated_at": datetime.now(UTC).isoformat(), "items": items, "all_pass": all(item["status"] == "PASS" for item in items)}


def main() -> None:
    output = Path("var/reports/master-70-item-checklist.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_checklist(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
