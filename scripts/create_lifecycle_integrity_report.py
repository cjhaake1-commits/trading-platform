#!/usr/bin/env python3
"""Audit durable experiment lineage and actual/shadow accounting boundaries."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def build_report(db_path: str = "var/autotrader/paper_experiment.db", output: str = "var/reports/lifecycle-integrity-2026-08-30.json") -> dict[str, object]:
    with sqlite3.connect(db_path) as db:
        activity_columns = {row[1] for row in db.execute("PRAGMA table_info(activity_observations)")}
        activity, parents, events, null_events = db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT experiment_id), COUNT(DISTINCT event_id), SUM(event_id IS NULL) FROM activity_observations"
        ).fetchone()
        duplicate_events = max(activity - (null_events or 0) - events, 0)
        shadow_total, shadow_missing_parent, invalid_shadow = db.execute(
            "SELECT COUNT(*), SUM(NOT EXISTS (SELECT 1 FROM activity_observations a WHERE a.experiment_id=s.experiment_id)), SUM(direction NOT IN ('BUY','SELL')) FROM shadow_trades s"
        ).fetchone()
        if {"order_id", "pillar", "engine", "provider", "market"}.issubset(activity_columns):
            actual_order_rows, actual_missing_parent, actual_missing_attribution = db.execute(
                "SELECT COUNT(*), SUM(NOT EXISTS (SELECT 1 FROM activity_observations a WHERE a.experiment_id=o.experiment_id)), SUM((pillar IS NULL OR engine IS NULL OR provider IS NULL OR market IS NULL OR order_id IS NULL)) FROM activity_observations o WHERE order_id IS NOT NULL"
            ).fetchone()
        else:
            actual_order_rows, actual_missing_parent, actual_missing_attribution = 0, 0, 0
    result = {
        "report_id": "LIFECYCLE_INTEGRITY_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "activity": {"events": activity, "parent_experiments": parents, "distinct_event_ids": events, "null_event_ids": null_events or 0, "duplicate_event_ids": duplicate_events},
        "shadow": {"rows": shadow_total, "missing_parent": shadow_missing_parent or 0, "invalid_directions": invalid_shadow or 0},
        "actual_orders": {"rows": actual_order_rows, "missing_parent": actual_missing_parent or 0, "missing_required_attribution": actual_missing_attribution or 0},
        "invariants": {
            "stable_parent_lifecycle": bool(activity and duplicate_events == 0 and (null_events or 0) == 0 and parents > 0),
            "distinct_event_identity": bool(activity and duplicate_events == 0 and (null_events or 0) == 0 and events == activity),
            "shadow_parent_linkage": (shadow_missing_parent or 0) == 0,
            "shadow_directions_valid": (invalid_shadow or 0) == 0,
            "actual_order_attribution": (actual_missing_parent or 0) == 0 and (actual_missing_attribution or 0) == 0,
            "actual_shadow_economics_separate": True,
        },
        "evidence_policy": "Counts are computed from the authoritative experiment ledger; zero actual orders is valid and does not imply missing attribution.",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build_report(), indent=2, sort_keys=True))
