#!/usr/bin/env python3
"""Persist measured forward-campaign coverage without inferring missing data."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")


def build_checkpoint(db_path: str = "var/autotrader/paper_experiment.db", now: datetime | None = None) -> dict[str, object]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = (current - timedelta(hours=24)).isoformat()
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute("SELECT pillar, candidate_status, occurred_at FROM activity_observations WHERE occurred_at >= ?", (cutoff,)).fetchall()
            shadows = connection.execute("SELECT exit_at, hypothetical_pnl FROM shadow_trades WHERE entry_at >= ?", (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        # A first-run or unavailable ledger is valid evidence of no observed
        # campaign data; the report must remain writable and explicit.
        rows, shadows = [], []
    shared_cycles = sum(row[1] == "CYCLE_COMPLETE" and row[0] == "Stocks/Crypto" for row in rows)
    counts = {}
    for engine in ENGINES:
        aliases = {engine, engine.lower()}
        selected = [row for row in rows if row[0] in aliases]
        counts[engine] = {"observations": len(selected), "cycles": sum(row[1] == "CYCLE_COMPLETE" for row in selected), "signals": sum(row[1] == "SIGNAL" for row in selected), "latest": max((row[2] for row in selected), default="UNKNOWN")}
    for engine in ("Stocks", "Crypto"):
        counts[engine]["cycles"] = "UNKNOWN"
        counts[engine]["shared_stocks_crypto_cycles"] = shared_cycles
    providers = {}
    for name, filename in (("Kalshi Predictions", "execution-predictions.json"), ("Kalshi Perps", "execution-perps.json")):
        path = Path("var/kalshi") / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            providers[name] = {"latest_observed_at": payload.get("observed_at", "UNKNOWN"), "state": payload.get("state", "UNKNOWN"), "scanned": payload.get("markets", payload.get("instruments", "UNKNOWN")), "orders": payload.get("orders", "UNKNOWN"), "fills": payload.get("fills", "UNKNOWN"), "historical_cycle_count": "UNKNOWN"}
        except (OSError, json.JSONDecodeError):
            providers[name] = {"latest_observed_at": "UNKNOWN", "state": "UNKNOWN", "scanned": "UNKNOWN", "orders": "UNKNOWN", "fills": "UNKNOWN", "historical_cycle_count": "UNKNOWN"}
    return {"report_id": "OVERNIGHT_FORWARD_CAMPAIGN", "generated_at": current.isoformat(), "window": "24h", "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper"}, "engines": counts, "providers": providers, "shadow": {"entries": len(shadows), "exits": sum(row[0] is not None for row in shadows), "completed_pnl": sum(float(row[1] or 0) for row in shadows if row[0] is not None)}, "evidence_policy": "UNKNOWN is retained when the authoritative source has no value; shared Stocks/Crypto cycle records are not assigned to either pillar, and a latest provider snapshot is never counted as historical campaign evidence."}


def write_checkpoint(output: str = "var/reports/overnight-forward-campaign.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_checkpoint(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_checkpoint())
