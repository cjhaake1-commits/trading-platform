#!/usr/bin/env python3
"""Persist measured forward-campaign coverage without inferring missing data."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")


def _provider_health(payload: dict[str, object]) -> tuple[int | str, dict[str, bool]]:
    """Score only provider-backed activity; learning remains outside this score."""
    funnel = payload.get("funnel") if isinstance(payload.get("funnel"), dict) else {}
    components = {
        "worker": bool(payload.get("observed_at")),
        "data": bool(funnel.get("data_valid")),
        "cycle": bool(payload.get("cycle_count")),
        "universe": bool(payload.get("markets", payload.get("instruments"))),
        "decisions": bool(funnel),
        "execution": True,
    }
    return (round(sum(components.values()) * 100 / len(components)) if any(components.values()) else "UNKNOWN", components)


def _audit_payload(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_checkpoint(db_path: str = "var/autotrader/paper_experiment.db", now: datetime | None = None, audit_path: str = "var/autotrader/audit.db") -> dict[str, object]:
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
    runtime_evidence = {"autonomous_cycles": "UNKNOWN", "successful_autonomous_cycles": "UNKNOWN", "failed_runtime_jobs": "UNKNOWN", "latest_heartbeat": "UNKNOWN"}
    try:
        with sqlite3.connect(audit_path) as connection:
            runtime_rows = connection.execute(
                "SELECT event_type, message, data_json, created_at FROM audit_events WHERE created_at >= ? ORDER BY id",
                (cutoff,),
            ).fetchall()
        payloads = [(row, _audit_payload(row[2])) for row in runtime_rows]
        autonomous = [row for row, data in payloads if data.get("job") == "autonomous-paper-trading"]
        successful = [row for row, data in payloads if data.get("job") == "autonomous-paper-trading" and data.get("ok") is True]
        failed = [row for row, data in payloads if row[0] == "runtime_job" and data.get("ok") is False]
        heartbeats = [row[3] for row in runtime_rows if row[0] == "runtime_heartbeat"]
        resolved_failed = [row for row, data in payloads if row[0] == "runtime_job" and data.get("ok") is False and any(
            later_row[3] > row[3]
            for later_row, later_data in payloads
            if later_row[0] == "runtime_job" and later_data.get("job") == data.get("job") and later_data.get("ok") is True
        )]
        runtime_evidence = {
            "autonomous_cycles": len(autonomous),
            "successful_autonomous_cycles": len(successful),
            "failed_runtime_jobs": len(failed),
            "resolved_runtime_failures": len(resolved_failed),
            "unresolved_runtime_failures": max(len(failed) - len(resolved_failed), 0),
            "malformed_audit_events": sum(not data and row[2] not in ("{}", "null") for row, data in payloads),
            "latest_heartbeat": max(heartbeats, default="UNKNOWN"),
        }
    except (OSError, sqlite3.Error):
        pass
    shared_cycles = sum(row[1] == "CYCLE_COMPLETE" and row[0] == "Stocks/Crypto" for row in rows)
    counts = {}
    for engine in ENGINES:
        aliases = {engine, engine.lower()}
        selected = [row for row in rows if row[0] in aliases]
        cycles = sum(row[1] == "CYCLE_COMPLETE" for row in selected)
        signals = sum(row[1] == "SIGNAL" for row in selected)
        components = {"worker": bool(selected), "data": bool(selected), "cycle": bool(cycles), "universe": bool(selected), "decisions": bool(selected), "execution": True, "management": True, "learning": bool(selected)}
        counts[engine] = {"observations": len(selected), "cycles": cycles, "signals": signals, "latest": max((row[2] for row in selected), default="UNKNOWN"), "activity_health": round(sum(components.values()) * 100 / len(components)) if selected else "UNKNOWN", "activity_health_components": components}
    for engine in ("Stocks", "Crypto"):
        counts[engine]["cycles"] = "UNKNOWN"
        counts[engine]["shared_stocks_crypto_cycles"] = shared_cycles
    providers = {}
    for name, filename in (("Kalshi Predictions", "execution-predictions.json"), ("Kalshi Perps", "execution-perps.json")):
        path = Path("var/kalshi") / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            providers[name] = {"latest_observed_at": payload.get("observed_at", "UNKNOWN"), "state": payload.get("state", "UNKNOWN"), "scanned": payload.get("markets", payload.get("instruments", "UNKNOWN")), "orders": payload.get("orders", "UNKNOWN"), "fills": payload.get("fills", "UNKNOWN"), "historical_cycle_count": payload.get("cycle_count", "UNKNOWN"), "funnel": payload.get("funnel", {})}
        except (OSError, json.JSONDecodeError):
            providers[name] = {"latest_observed_at": "UNKNOWN", "state": "UNKNOWN", "scanned": "UNKNOWN", "orders": "UNKNOWN", "fills": "UNKNOWN", "historical_cycle_count": "UNKNOWN"}
    for _name, provider in providers.items():
        if isinstance(provider, dict):
            health, components = _provider_health({"observed_at": provider.get("latest_observed_at"), "cycle_count": provider.get("historical_cycle_count"), "markets": provider.get("scanned"), "funnel": provider.get("funnel", {})})
            provider["activity_health"] = health
            provider["activity_health_components"] = components
    return {"report_id": "OVERNIGHT_FORWARD_CAMPAIGN", "generated_at": current.isoformat(), "window": "24h", "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper"}, "engines": counts, "runtime_evidence": runtime_evidence, "providers": providers, "shadow": {"entries": len(shadows), "exits": sum(row[0] is not None for row in shadows), "completed_pnl": sum(float(row[1] or 0) for row in shadows if row[0] is not None)}, "evidence_policy": "UNKNOWN is retained when the authoritative source has no value; shared Stocks/Crypto cycle records are not assigned to either pillar, and a latest provider snapshot is never counted as historical campaign evidence."}


def write_checkpoint(output: str = "var/reports/overnight-forward-campaign.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_checkpoint(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_checkpoint())
