#!/usr/bin/env python3
"""Write a durable, evidence-only overnight progress checkpoint."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.verify_paper_safety import verify
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_paper_safety import verify


def _json(path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _streamlit_http_status() -> int | str:
    """Record dashboard reachability without failing the progress job."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8501", timeout=3) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return "UNKNOWN"


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
        "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper", "verifier": verify()},
        "runtime": {"healthy": status.get("healthy", "UNKNOWN"), "heartbeat": status.get("last_heartbeat_at", "UNKNOWN"), "execution_state": status.get("execution_state", "UNKNOWN"), "streamlit_http": _streamlit_http_status()},
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
