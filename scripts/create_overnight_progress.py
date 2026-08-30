#!/usr/bin/env python3
"""Write a durable, evidence-only overnight progress checkpoint."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _json(path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_progress() -> dict[str, object]:
    activity = {"events": "UNKNOWN", "parent_experiments": "UNKNOWN", "event_ids": "UNKNOWN"}
    shadows = {"entries": "UNKNOWN", "exits": "UNKNOWN", "invalid_directions": "UNKNOWN"}
    try:
        with sqlite3.connect("var/autotrader/paper_experiment.db") as connection:
            activity["events"], activity["parent_experiments"], activity["event_ids"] = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT experiment_id), COUNT(DISTINCT event_id) FROM activity_observations"
            ).fetchone()
            shadows["entries"], shadows["exits"], shadows["invalid_directions"] = connection.execute(
                "SELECT COUNT(*), SUM(exit_at IS NOT NULL), SUM(direction NOT IN ('BUY','SELL')) FROM shadow_trades"
            ).fetchone()
    except sqlite3.Error:
        pass
    status = _json("var/autotrader/status.json")
    telemetry = {}
    for family in ("predictions", "perps"):
        path = Path(f"var/kalshi/candidate-telemetry-{family}.jsonl")
        telemetry[family] = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else "UNKNOWN"
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "UNKNOWN"
    return {
        "report_id": "OVERNIGHT_PROGRESS",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": sha,
        "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper"},
        "runtime": {"healthy": status.get("healthy", "UNKNOWN"), "heartbeat": status.get("last_heartbeat_at", "UNKNOWN"), "execution_state": status.get("execution_state", "UNKNOWN")},
        "activity": activity,
        "shadow": shadows,
        "kalshi_candidate_telemetry_rows": telemetry,
        "artifacts": {name: Path(path).exists() for name, path in {
            "daily_learning": "var/reports/daily-learning-2026-08-30.json",
            "forward_campaign": "var/reports/overnight-forward-campaign.json",
            "error_ledger": "var/reports/overnight-errors.json",
        }.items()},
        "evidence_policy": "This is a progress checkpoint, not an acceptance claim; UNKNOWN is retained when evidence is unavailable.",
    }


def write_progress(output: str = "var/reports/overnight-progress.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_progress(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_progress())
