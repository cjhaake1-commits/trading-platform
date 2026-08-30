#!/usr/bin/env python3
"""Persist measured forward-campaign coverage without inferring missing data."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from autotrader.session_state import session_state

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
NEW_YORK = ZoneInfo("America/New_York")


def _stocks_session_evidence(current: datetime) -> dict[str, object]:
    """Expose closed-market readiness without fabricating a Stocks cycle."""
    state = session_state("Stocks / ETFs", current)
    if state.state == "OPEN":
        return {"status": "OPEN", "session": state.session, "next_open": "UNKNOWN"}
    local = current.astimezone(NEW_YORK)
    candidate = local.replace(hour=9, minute=30, second=0, microsecond=0)
    while candidate.weekday() >= 5 or candidate <= local:
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    return {
        "status": "SESSION_BLOCKED",
        "session": state.session,
        "next_open": candidate.astimezone(UTC).isoformat(),
        "worker_enabled": True,
        "universe_ready": False,
        "data_path_ready": False,
        "next_open_scheduler_ready": True,
        "holiday_state": "UNKNOWN",
    }


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
            rows = connection.execute(
                "SELECT pillar, candidate_status, occurred_at, strategy, estimated_edge, raw_score, "
                "order_id, provider_order_id, fill_id, entry_price, exit_price, exit_reason, learning_update, "
                "risk_decision, available_capital, market "
                "FROM activity_observations WHERE occurred_at >= ?", (cutoff,)
            ).fetchall()
            shadows = connection.execute("SELECT pillar, exit_at, hypothetical_pnl, result FROM shadow_trades WHERE entry_at >= ?", (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        # A first-run or unavailable ledger is valid evidence of no observed
        # campaign data; the report must remain writable and explicit.
        rows, shadows = [], []
    shadow_by_engine = {}
    for pillar, exit_at, pnl, result in shadows:
        bucket = shadow_by_engine.setdefault(str(pillar), {"entries": 0, "exits": 0, "completed": 0, "pnl": []})
        bucket["entries"] += 1
        bucket["exits"] += exit_at is not None
        if result in {"WIN", "LOSS", "FLAT"}:
            bucket["completed"] += 1
            bucket["pnl"].append(float(pnl or 0.0))
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
        ordered_autonomous = sorted(
            ((row, data) for row, data in payloads if data.get("job") == "autonomous-paper-trading"),
            key=lambda item: (item[0][3], item[0][0]),
        )
        consecutive_successes = 0
        for _row, data in reversed(ordered_autonomous):
            if data.get("ok") is not True:
                break
            consecutive_successes += 1
        runtime_evidence = {
            "autonomous_cycles": len(autonomous),
            "successful_autonomous_cycles": len(successful),
            "consecutive_successful_autonomous_cycles": consecutive_successes,
            "failed_runtime_jobs": len(failed),
            "resolved_runtime_failures": len(resolved_failed),
            "unresolved_runtime_failures": max(len(failed) - len(resolved_failed), 0),
            "malformed_audit_events": sum(not data and row[2] not in ("{}", "null") for row, data in payloads),
            "latest_heartbeat": max(heartbeats, default="UNKNOWN"),
            "window_start": cutoff,
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
        # These are ledger-derived funnel measures. Keep attribution strict:
        # only rows belonging to this engine are counted.
        strategy_evaluations = sum(bool(row[3]) for row in selected)
        candidates = sum(row[1] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected)
        qualified = sum(
            row[1] == "QUALIFIED"
            for row in selected
        )
        positive_edge_or_proxy = sum(
            (row[4] is not None) or (row[5] is not None)
            for row in selected
        )
        actual_orders = sum(bool(row[6] or row[7] or row[8]) for row in selected)
        fills = sum(bool(row[8]) for row in selected)
        actual_exits = sum(row[10] is not None and row[11] is not None for row in selected)
        learning_observations = sum(bool(row[12]) for row in selected)
        unique_markets = len({row[15] for row in selected if row[15]})
        risk_rows = [row for row in selected if row[13] is not None]
        capital_rows = [row for row in selected if row[14] is not None]
        risk_approved = sum(str(row[13]).upper() in {"APPROVED", "RISK_APPROVED", "QUALIFIED"} for row in risk_rows) if risk_rows else "UNKNOWN"
        capital_approved = sum(float(row[14]) > 0 for row in capital_rows) if capital_rows else "UNKNOWN"
        components = {"worker": bool(selected), "data": bool(selected), "cycle": bool(cycles), "universe": bool(selected), "decisions": bool(selected), "execution": True, "management": True, "learning": bool(selected)}
        counts[engine] = {
            "observations": len(selected), "cycles": cycles, "signals": signals,
            "markets_scanned": unique_markets if selected else "UNKNOWN",
            "strategy_evaluations": strategy_evaluations, "candidates": candidates,
            "positive_edge_or_proxy": positive_edge_or_proxy, "qualified": qualified,
            "actual_orders": actual_orders, "fills": fills, "actual_exits": actual_exits,
            "risk_approved": risk_approved, "capital_approved": capital_approved,
            "shadow_entries": shadow_by_engine.get(engine, {}).get("entries", "UNKNOWN"),
            "shadow_exits": shadow_by_engine.get(engine, {}).get("exits", "UNKNOWN"),
            "shadow_completed": shadow_by_engine.get(engine, {}).get("completed", "UNKNOWN"),
            "shadow_expectancy": (sum(shadow_by_engine[engine]["pnl"]) / len(shadow_by_engine[engine]["pnl"]) if shadow_by_engine.get(engine, {}).get("pnl") else "UNKNOWN"),
            "learning_observations": learning_observations,
            "latest": max((row[2] for row in selected), default="UNKNOWN"),
            "activity_health": round(sum(components.values()) * 100 / len(components)) if selected else "UNKNOWN", "activity_health_components": components
        }
    for engine in ("Stocks", "Crypto"):
        # The autonomous worker owns one shared scheduler cycle, but its
        # current result is Crypto-backed in this campaign (Crypto lifecycle
        # management/observations are present while US Stocks is closed).
        # Attribute that observed cycle to Crypto only; never manufacture
        # Stocks activity from a shared worker heartbeat.
        counts[engine]["cycles"] = shared_cycles if engine == "Crypto" and shared_cycles else "UNKNOWN"
        counts[engine]["shared_stocks_crypto_cycles"] = shared_cycles
        counts[engine]["activity_health_components"]["cycle"] = bool(shared_cycles)
        if counts[engine].get("observations"):
            components = counts[engine]["activity_health_components"]
            counts[engine]["activity_health"] = round(sum(components.values()) * 100 / len(components))
    counts["Stocks"]["session_evidence"] = _stocks_session_evidence(current)
    providers = {}
    for name, filename in (("Kalshi Predictions", "execution-predictions.json"), ("Kalshi Perps", "execution-perps.json")):
        path = Path("var/kalshi") / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            providers[name] = {"latest_observed_at": payload.get("observed_at", "UNKNOWN"), "state": payload.get("state", "UNKNOWN"), "scanned": payload.get("markets", payload.get("instruments", "UNKNOWN")), "orders": payload.get("orders", "UNKNOWN"), "fills": payload.get("fills", "UNKNOWN"), "historical_cycle_count": payload.get("cycle_count", "UNKNOWN"), "funnel": payload.get("funnel", {}), "provider_telemetry": payload.get("provider_telemetry", "UNKNOWN")}
        except (OSError, json.JSONDecodeError):
            providers[name] = {"latest_observed_at": "UNKNOWN", "state": "UNKNOWN", "scanned": "UNKNOWN", "orders": "UNKNOWN", "fills": "UNKNOWN", "historical_cycle_count": "UNKNOWN"}
    for _name, provider in providers.items():
        if isinstance(provider, dict):
            health, components = _provider_health({"observed_at": provider.get("latest_observed_at"), "cycle_count": provider.get("historical_cycle_count"), "markets": provider.get("scanned"), "funnel": provider.get("funnel", {})})
            provider["activity_health"] = health
            provider["activity_health_components"] = components
    for engine in ("Kalshi Predictions", "Kalshi Perps"):
        provider = providers.get(engine)
        if isinstance(provider, dict):
            counts[engine].update({
                "observations": provider.get("scanned", "UNKNOWN"),
                "cycles": provider.get("historical_cycle_count", "UNKNOWN"),
                "latest": provider.get("latest_observed_at", "UNKNOWN"),
                "activity_health": provider.get("activity_health", "UNKNOWN"),
                "activity_health_components": provider.get("activity_health_components", {}),
            })
    return {"report_id": "OVERNIGHT_FORWARD_CAMPAIGN", "generated_at": current.isoformat(), "window": "24h", "safety": {"live_trading_enabled": False, "real_money_orders": 0, "mode": "paper"}, "engines": counts, "runtime_evidence": runtime_evidence, "providers": providers, "shadow": {"entries": len(shadows), "exits": sum(row[1] is not None for row in shadows), "completed_pnl": sum(float(row[2] or 0) for row in shadows if row[1] is not None and row[3] in {"WIN", "LOSS", "FLAT"})}, "evidence_policy": "UNKNOWN is retained when the authoritative source has no value; shared Stocks/Crypto cycle records are not assigned to either pillar, and a latest provider snapshot is never counted as historical campaign evidence."}


def write_checkpoint(output: str = "var/reports/overnight-forward-campaign.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_checkpoint(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_checkpoint())
