"""Durable paper economic lifecycle state with idempotent release accounting."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Mapping

STAGES = ("DECISION", "ORDER_INTENT", "ORDER", "ACK", "FILL", "OWNERSHIP", "MANAGEMENT", "EXIT_DECISION", "EXIT_INTENT", "EXIT_ACK", "EXIT_FILL", "OUTCOME", "LEARNING")
PROTECTED = {"UNKNOWN", "LEGACY", "EXTERNAL"}


class EconomicLifecycle:
    def __init__(self, path: str | Path = "var/autotrader/economic-lifecycle.db") -> None:
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, trade_id TEXT, stage TEXT, ownership TEXT, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS releases (trade_id TEXT PRIMARY KEY, amount REAL NOT NULL, realized_pnl REAL, released_at TEXT NOT NULL)")

    def event(self, trade_id: str, stage: str, payload: Mapping[str, object]) -> bool:
        if stage not in STAGES: raise ValueError("invalid lifecycle stage")
        ownership = str(payload.get("ownership") or "UNKNOWN").upper()
        if stage in {"OWNERSHIP", "MANAGEMENT", "EXIT_DECISION", "EXIT_INTENT", "EXIT_ACK", "EXIT_FILL", "OUTCOME", "LEARNING"} and ownership in PROTECTED:
            return False
        import json
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)", (f"{trade_id}:{stage}", trade_id, stage, ownership, json.dumps(dict(payload), sort_keys=True, default=str)))
        return True

    def release(self, trade_id: str, *, amount: float, realized_pnl: float | None, released_at: str) -> bool:
        if amount < 0: raise ValueError("released capital cannot be negative")
        with sqlite3.connect(self.path) as db:
            if db.execute("SELECT 1 FROM releases WHERE trade_id=?", (trade_id,)).fetchone(): return False
            if not db.execute("SELECT 1 FROM events WHERE event_id=? AND stage='EXIT_FILL' AND ownership='PLATFORM_OWNED'", (f"{trade_id}:EXIT_FILL",)).fetchone(): return False
            db.execute("INSERT INTO releases VALUES (?,?,?,?)", (trade_id, amount, realized_pnl, released_at))
        return True

    def metrics(self) -> dict[str, float]:
        with sqlite3.connect(self.path) as db:
            released, pnl = db.execute("SELECT COALESCE(SUM(amount),0), COALESCE(SUM(realized_pnl),0) FROM releases").fetchone()
            outcomes = db.execute("SELECT COUNT(*) FROM events WHERE stage='OUTCOME' AND ownership='PLATFORM_OWNED'").fetchone()[0]
            redeployed = db.execute("SELECT COALESCE(SUM(CAST(json_extract(payload, '$.capital_required') AS REAL)),0) FROM events WHERE stage='ORDER_INTENT' AND ownership='PLATFORM_OWNED'").fetchone()[0]
        return {"capital_released": float(released), "realized_pnl": float(pnl),
                "completed_outcomes": int(outcomes), "capital_redeployed": float(redeployed),
                "available_released_capital": max(float(released) - float(redeployed), 0.0)}
