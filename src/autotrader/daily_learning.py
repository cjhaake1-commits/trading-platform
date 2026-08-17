from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .runtime import JobResult


@dataclass
class DailyLearningJob:
    """Persist a daily evidence journal from autonomous paper-trading activity.

    This job intentionally does not modify hard risk controls. It creates the
    durable dataset used for later bounded strategy tuning once enough completed
    trades exist to estimate expectancy reliably.
    """

    audit_db: str = "var/autotrader/audit.db"
    output_path: str = "var/autotrader/learning/daily_learning.jsonl"
    cadence_seconds: float = 3600.0
    name: str = "daily-learning"

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        day = now.astimezone(UTC).date()
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)

        path = Path(self.audit_db)
        if not path.exists():
            return JobResult(True, "Daily learning journal waiting for audit data", {"date": day.isoformat()})

        with sqlite3.connect(path) as con:
            rows = con.execute(
                """
                SELECT message, data_json, created_at
                FROM audit_events
                WHERE created_at >= ? AND created_at < ?
                ORDER BY id ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()

        cycles = 0
        scans = {"equities": 0, "forex": 0, "crypto": 0}
        qualified = {"equities": 0, "forex": 0, "crypto": 0}
        entries: list[dict[str, object]] = []
        exits: list[dict[str, object]] = []
        risk_rejections: list[dict[str, object]] = []
        submission_failures: list[dict[str, object]] = []
        duplicate_skips: list[dict[str, object]] = []
        sizing_skips: list[dict[str, object]] = []

        for message, raw, _created_at in rows:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if "Autonomous paper cycle" not in str(message):
                continue
            cycles += 1
            scans["forex"] += int(data.get("forex_scanned") or 0)
            scans["crypto"] += int(data.get("crypto_scanned") or 0)
            total_scanned = int(data.get("scanned") or 0)
            scans["equities"] += max(total_scanned - int(data.get("forex_scanned") or 0) - int(data.get("crypto_scanned") or 0), 0)
            qualified["equities"] += int(data.get("equity_qualified") or 0)
            qualified["forex"] += int(data.get("forex_qualified") or 0)
            qualified["crypto"] += int(data.get("crypto_qualified") or 0)
            entries.extend(data.get("entries") or [])
            exits.extend(data.get("exits") or [])
            risk_rejections.extend(data.get("risk_rejections") or [])
            submission_failures.extend(data.get("submission_failures") or [])
            duplicate_skips.extend(data.get("duplicate_skips") or [])
            sizing_skips.extend(data.get("sizing_skips") or [])

        record = {
            "date": day.isoformat(),
            "generated_at": now.astimezone(UTC).isoformat(),
            "cycles": cycles,
            "scans": scans,
            "qualified": qualified,
            "entries": entries,
            "exits": exits,
            "risk_rejections": risk_rejections,
            "submission_failures": submission_failures,
            "duplicate_skips": duplicate_skips,
            "sizing_skips": sizing_skips,
            "hard_guardrails_mutable": False,
            "learning_status": "collecting_evidence",
            "note": "Daily evidence is persisted for bounded tuning; no risk limit is self-modified.",
        }

        output = Path(self.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, object]] = []
        if output.exists():
            for line in output.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and item.get("date") != day.isoformat():
                    existing.append(item)
        existing.append(record)
        output.write_text("\n".join(json.dumps(item, sort_keys=True, default=str) for item in existing) + "\n", encoding="utf-8")

        return JobResult(
            True,
            "Daily paper-trading learning journal updated",
            {
                "date": day.isoformat(),
                "cycles": cycles,
                "entry_count": len(entries),
                "exit_count": len(exits),
                "submission_failure_count": len(submission_failures),
                "learning_status": "collecting_evidence",
                "output_path": str(output),
            },
        )
