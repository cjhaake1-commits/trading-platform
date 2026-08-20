from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .learning import RealizedOutcomeLearner
from .runtime import JobResult


@dataclass
class DailyLearningJob:
    """Persist daily evidence and update bounded learned entry parameters."""

    audit_db: str = "var/autotrader/audit.db"
    ledger_path: str = "var/autotrader/portfolio.db"
    output_path: str = "var/autotrader/learning/daily_learning.jsonl"
    cadence_seconds: float = 3600.0
    name: str = "daily-learning"

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        day = now.astimezone(UTC).date()
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)

        path = Path(self.audit_db)
        rows = []
        if path.exists():
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
        scans = {"equities": 0, "forex": 0, "crypto": 0, "metals": 0, "international": 0}
        qualified = {"equities": 0, "forex": 0, "crypto": 0, "metals": 0, "international": 0}
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
            if not isinstance(data, dict) or "Autonomous paper cycle" not in str(message):
                continue
            cycles += 1
            fx = int(data.get("forex_scanned") or 0)
            crypto = int(data.get("crypto_scanned") or 0)
            total = int(data.get("scanned") or 0)
            scans["forex"] += fx
            scans["crypto"] += crypto
            scans["equities"] += max(total - fx - crypto, 0)
            qualified["equities"] += int(data.get("equity_qualified") or 0)
            qualified["forex"] += int(data.get("forex_qualified") or 0)
            qualified["crypto"] += int(data.get("crypto_qualified") or 0)
            entries.extend(data.get("entries") or [])
            exits.extend(data.get("exits") or [])
            risk_rejections.extend(data.get("risk_rejections") or [])
            submission_failures.extend(data.get("submission_failures") or [])
            duplicate_skips.extend(data.get("duplicate_skips") or [])
            sizing_skips.extend(data.get("sizing_skips") or [])

        learning = RealizedOutcomeLearner(ledger_path=self.ledger_path).update(now)
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
            "learning_status": learning["sample_status"],
            "performance": learning,
        }
        output = Path(self.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if output.exists():
            for line in output.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and item.get("date") != day.isoformat():
                    existing.append(item)
        existing.append(record)
        serialized = "\n".join(json.dumps(item, sort_keys=True, default=str) for item in existing)
        output.write_text(serialized + "\n", encoding="utf-8")
        return JobResult(
            True,
            "Daily paper-trading learning updated",
            {
                "date": day.isoformat(),
                "cycles": cycles,
                "entry_count": len(entries),
                "exit_count": len(exits),
                "completed_trades": learning["completed_trades"],
                "learning_status": learning["sample_status"],
                "parameter_changes": learning["changes"],
                "hard_guardrails_mutable": False,
            },
        )
