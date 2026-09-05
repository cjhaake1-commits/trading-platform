"""Append-only forward lifecycle attribution with protected ownership rules."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping

STAGES = ("CANDIDATE", "DECISION", "ORDER_INTENT", "ORDER", "ACK", "FILL", "OWNERSHIP", "MANAGEMENT", "EXIT_DECISION", "EXIT_ORDER", "EXIT_ACK", "EXIT_FILL", "OUTCOME", "LEARNING")
PROTECTED = {"UNKNOWN", "LEGACY", "EXTERNAL"}


class ForwardLifecycle:
    def __init__(self, path: str | Path = "var/autotrader/forward-lifecycle.db") -> None:
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS lifecycle_events (
                event_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, stage TEXT NOT NULL,
                occurred_at TEXT NOT NULL, pillar TEXT NOT NULL, engine TEXT NOT NULL,
                instrument TEXT NOT NULL, ownership TEXT, payload_json TEXT NOT NULL)""")

    def record(self, *, trade_id: str, stage: str, occurred_at: str, pillar: str,
               engine: str, instrument: str, payload: Mapping[str, object] | None = None) -> bool:
        if stage not in STAGES: raise ValueError(f"unknown lifecycle stage: {stage}")
        data = dict(payload or {})
        ownership = str(data.get("ownership") or "UNKNOWN").upper()
        if stage in {"OWNERSHIP", "MANAGEMENT", "EXIT_DECISION", "EXIT_ORDER", "EXIT_ACK", "EXIT_FILL", "OUTCOME", "LEARNING"} and ownership in PROTECTED:
            return False
        event_id = f"{trade_id}:{stage}"
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR IGNORE INTO lifecycle_events VALUES (?,?,?,?,?,?,?,?,?)",
                       (event_id, trade_id, stage, occurred_at, pillar, engine, instrument, ownership, json.dumps(data, sort_keys=True, default=str)))
        return True

    def counts(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT stage, COUNT(*) FROM lifecycle_events GROUP BY stage").fetchall()
        return {stage: next((int(n) for s, n in rows if s == stage), 0) for stage in STAGES}
