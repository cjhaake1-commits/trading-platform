#!/usr/bin/env python3
"""Materialize authoritative runtime exception evidence for overnight review."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def build_error_ledger(audit_path: str = "var/autotrader/audit.db", *, now: datetime | None = None, hours: int = 24) -> dict[str, object]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = (current - timedelta(hours=hours)).isoformat()
    try:
        with sqlite3.connect(audit_path) as connection:
            rows = connection.execute(
                "SELECT event_type, message, data_json, created_at FROM audit_events WHERE created_at >= ? ORDER BY id",
                (cutoff,),
            ).fetchall()
    except (OSError, sqlite3.Error):
        rows = []
    errors = []
    for event_type, message, data_json, created_at in rows:
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError:
            data = {}
        if event_type != "runtime_job" or data.get("ok") is not False:
            continue
        errors.append({
            "timestamp": created_at,
            "component": "autonomous-runtime",
            "engine": data.get("job", "UNKNOWN"),
            "exception_type": data.get("exception_type", "JobResultFailure"),
            "message": message,
            "root_cause": data.get("error") or message,
            "repair": data.get("repair", "UNKNOWN"),
            "regression_test": data.get("regression_test", "UNKNOWN"),
            "commit": data.get("commit", "UNKNOWN"),
            "resolved": bool(data.get("resolved", False)),
        })
    return {
        "report_id": "OVERNIGHT_ERROR_LEDGER",
        "generated_at": current.isoformat(),
        "window_hours": hours,
        "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper"},
        "errors": errors,
        "evidence_policy": "Only failed runtime jobs in the authoritative audit store are included; missing repair metadata remains UNKNOWN.",
    }


def write_error_ledger(*, audit_path: str = "var/autotrader/audit.db", output: str = "var/reports/overnight-errors.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_error_ledger(audit_path), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_error_ledger())
