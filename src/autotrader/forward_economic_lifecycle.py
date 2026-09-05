"""Durable paper economic lifecycle state with idempotent release accounting."""
from __future__ import annotations

import sqlite3
import json
from datetime import datetime
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

    def velocity_metrics(self) -> dict[str, float | None]:
        """Calculate release/redeployment velocity from economic event timestamps."""
        with sqlite3.connect(self.path) as db:
            releases = db.execute("SELECT trade_id, amount, released_at FROM releases ORDER BY released_at").fetchall()
            intents = db.execute("SELECT trade_id, payload FROM events WHERE stage='ORDER_INTENT' AND ownership='PLATFORM_OWNED' ORDER BY event_id").fetchall()
        redeployed = sum(float(json.loads(payload).get("capital_required") or 0.0) for _, payload in intents)
        latencies = []
        for _, _, released_at in releases:
            try:
                released = datetime.fromisoformat(str(released_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            for _, payload in intents:
                try:
                    allocated_at = datetime.fromisoformat(str(json.loads(payload).get("occurred_at")).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue
                if allocated_at >= released:
                    latencies.append((allocated_at - released).total_seconds())
                    break
        released_total = sum(float(row[1]) for row in releases)
        return {"capital_released": released_total, "capital_redeployed": redeployed,
                "average_time_to_redeploy": sum(latencies) / len(latencies) if latencies else None,
                "capital_turnover": redeployed / released_total if released_total else 0.0,
                "capital_velocity": len(latencies) / max((datetime.now().astimezone() - datetime.fromisoformat(str(releases[0][2]).replace("Z", "+00:00"))).total_seconds() / 86400, 1.0) if releases else 0.0,
                "return_on_deployed_capital": None}
