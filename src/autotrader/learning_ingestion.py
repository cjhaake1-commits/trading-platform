"""Validated forward outcome ingestion for the Learning Tree."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Mapping


class LearningIngestor:
    def __init__(self, path: str | Path = "var/autotrader/learning/forward-outcomes.db") -> None:
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS outcomes (
                outcome_id TEXT PRIMARY KEY, strategy TEXT, pillar TEXT, instrument TEXT,
                regime TEXT, direction TEXT, ownership TEXT, decision_at TEXT,
                outcome_at TEXT, realized_pnl REAL, payload_json TEXT NOT NULL)""")

    def ingest(self, *, outcome_id: str, outcome: Mapping[str, object]) -> bool:
        ownership = str(outcome.get("ownership") or "UNKNOWN").upper()
        if ownership != "PLATFORM_OWNED": return False
        decision_at = outcome.get("decision_at"); outcome_at = outcome.get("outcome_at")
        if not decision_at or not outcome_at or datetime.fromisoformat(str(outcome_at).replace("Z", "+00:00")) < datetime.fromisoformat(str(decision_at).replace("Z", "+00:00")):
            return False
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (outcome_id, str(outcome.get("strategy") or "UNKNOWN"), str(outcome.get("pillar") or "UNKNOWN"), str(outcome.get("instrument") or "UNKNOWN"), str(outcome.get("regime") or "UNKNOWN"), str(outcome.get("direction") or "UNKNOWN"), ownership, str(decision_at), str(outcome_at), outcome.get("realized_pnl"), json.dumps(dict(outcome), sort_keys=True, default=str)))
        return cur.rowcount == 1

    def count(self) -> int:
        with sqlite3.connect(self.path) as db: return int(db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0])

    def strategy_health(self, *, minimum_sample: int = 30) -> list[dict[str, object]]:
        """Aggregate only clean platform-owned forward outcomes for governance."""
        from .strategy_health import assess_strategy_health
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT strategy, COUNT(*), AVG(realized_pnl) FROM outcomes WHERE ownership='PLATFORM_OWNED' GROUP BY strategy").fetchall()
        return [{**assess_strategy_health(str(strategy), "v1", int(sample), float(expectancy) if expectancy is not None else None, minimum_sample=minimum_sample), "source": "CLEAN_FORWARD_PAPER_OUTCOMES"} for strategy, sample, expectancy in rows]

    def publish_strategy_health(self, path: str | Path = "var/reports/strategy-health.json", *, minimum_sample: int = 30) -> dict[str, object]:
        payload = {"strategies": self.strategy_health(minimum_sample=minimum_sample), "evidence_scope": "FORWARD_PAPER_PLATFORM_OWNED_ONLY", "minimum_sample": minimum_sample}
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        return payload
