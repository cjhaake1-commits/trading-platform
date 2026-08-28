"""Durable, paper-only lane evidence and cash-efficiency summaries."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

LANES = ("BASELINE", "DAY_TRADE", "SHORT", "DERIVATIVE_SIM", "ARBITRAGE_SIM")
STATUSES = ("CANDIDATE", "QUALIFIED", "REJECTED", "EXECUTED", "SIMULATED", "OPEN", "CLOSED")


class PaperLaneLedger:
    def __init__(self, path: str | Path = "var/autotrader/learning/paper-lanes.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS lane_events (
                id INTEGER PRIMARY KEY, timestamp TEXT, pillar TEXT, lane TEXT, strategy TEXT,
                symbol TEXT, direction TEXT, provider TEXT, timeframe TEXT, mode TEXT,
                candidate_score REAL, confidence REAL, gross_expected_edge REAL,
                estimated_costs REAL, net_expected_edge REAL, capital_committed REAL,
                notional_exposure REAL, entry REAL, exit REAL, holding_time REAL,
                gross_pnl REAL, fees REAL, net_realized_pnl REAL, simulated_pnl REAL,
                mfe REAL, mae REAL, exit_reason TEXT, market_regime TEXT, status TEXT)""")

    def record(self, **event: object) -> None:
        event.setdefault("timestamp", datetime.now(UTC).isoformat())
        event.setdefault("status", "CANDIDATE")
        event.setdefault("mode", "PAPER_RESEARCH")
        lane = str(event.get("lane", ""))
        if lane not in LANES or str(event["status"]) not in STATUSES:
            raise ValueError("unsupported paper lane or status")
        columns = ("timestamp","pillar","lane","strategy","symbol","direction","provider","timeframe","mode","candidate_score","confidence","gross_expected_edge","estimated_costs","net_expected_edge","capital_committed","notional_exposure","entry","exit","holding_time","gross_pnl","fees","net_realized_pnl","simulated_pnl","mfe","mae","exit_reason","market_regime","status")
        values = [event.get(c) for c in columns]
        with sqlite3.connect(self.path) as db:
            db.execute(f"INSERT INTO lane_events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)

    def summary(self) -> dict[str, dict[str, float | int | None]]:
        out = {}
        with sqlite3.connect(self.path) as db:
            for lane in LANES:
                rows = db.execute("SELECT status, net_realized_pnl, simulated_pnl, fees, capital_committed, holding_time, exit_reason FROM lane_events WHERE lane=?", (lane,)).fetchall()
                realized = sum(float(r[1] or 0) for r in rows)
                simulated = sum(float(r[2] or 0) for r in rows)
                closed = [r for r in rows if r[0] == "CLOSED"]
                qualified = [r for r in rows if r[0] in {"QUALIFIED", "EXECUTED", "SIMULATED", "OPEN", "CLOSED"}]
                wins = [r for r in closed if float(r[1] or r[2] or 0) > 0]
                losses = [r for r in closed if float(r[1] or r[2] or 0) < 0]
                blocked = [r for r in rows if "CAPABILITY_BLOCKED" in str(r[6] or "")]
                state = "CAPABILITY_BLOCKED" if blocked and not qualified else ("COLLECTING" if not qualified else "ACTIVE")
                out[lane] = {"state": state, "sample_size": len(closed), "candidates": len(rows), "qualified": len(qualified), "executed": sum(r[0] == "EXECUTED" for r in rows), "simulated": sum(r[0] == "SIMULATED" for r in rows), "open": sum(r[0] == "OPEN" for r in rows), "closed": len(closed), "wins": len(wins), "losses": len(losses), "net_realized_pnl": realized, "simulated_pnl": simulated, "fees": sum(float(r[3] or 0) for r in rows), "capital_committed": sum(float(r[4] or 0) for r in rows), "notional_exposure": 0.0, "average_hold": (sum(float(r[5] or 0) for r in closed) / len(closed) if closed else 0.0), "expectancy": realized / len(closed) if closed else 0.0, "profit_factor": (sum(float(r[1] or r[2] or 0) for r in wins) / abs(sum(float(r[1] or r[2] or 0) for r in losses)) if losses else 0.0), "drawdown": 0.0, "capital_turns": 0.0, "return_per_dollar": realized / sum(float(r[4] or 0) for r in closed) if closed and sum(float(r[4] or 0) for r in closed) else 0.0, "return_per_hour": 0.0, "last_update": datetime.now(UTC).isoformat(), "blocker_reason": str(blocked[-1][6]) if blocked else None}
        return out

    def write_summary(self, path: str | Path = "var/autotrader/learning/paper-lane-summary.json") -> dict[str, object]:
        summary = self.summary()
        ranked = sorted(summary, key=lambda k: float(summary[k]["net_realized_pnl"]), reverse=True)
        payload = {"updated_at": datetime.now(UTC).isoformat(), "paper_only": True, "lanes": summary, "best_realized_cash_generator": ranked[0] if ranked else None, "champion": "BASELINE", "eligible_challengers": [], "multipliers": {lane: 1.0 for lane in LANES}, "note": "allocation changes require minimum samples and cost-adjusted realized evidence"}
        Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload
