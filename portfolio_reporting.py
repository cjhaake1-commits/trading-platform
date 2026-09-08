"""Read-only, freshness-aware accounting contract shared by app and publisher.

Missing values never become zero. Broker balances, notional, allocated budgets
and income are different measurements. This module cannot submit any order.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from runtime_income_evidence import capital_diagnostics, cycle_evidence

REPORT_VERSION = "income-report-v1"
POLICY_VERSION = "income_6000_v1"
MAX_AGE_SECONDS = 300
PILLARS = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi")
ALIASES = {
    "US Stocks / ETFs": "Stocks", "stocks": "Stocks", "alpaca_equities": "Stocks",
    "crypto": "Crypto", "alpaca_crypto": "Crypto", "forex": "Forex", "oanda_fx": "Forex",
    "Metals/Commodities": "Metals", "Metals / Commodities": "Metals", "alpaca_metals": "Metals",
    "metals": "Metals", "international": "International", "ibkr_global": "International",
    "kalshi": "Kalshi",
}
FIELDS = {
    "equity": "economic_equity", "deployed": "deployed_cash", "available": "available_cash",
    "pending": "pending", "position_market_value": "position_market_value",
    "realized_today": "realized_today", "unrealized": "unrealized", "total_pnl": "total_pnl",
    "positions": "positions", "working_orders": "working_orders", "fills_today": "trades_today",
}
JOBS = {
    "Stocks": "autonomous-paper-trading", "Crypto": "autonomous-paper-trading",
    "Forex": "oanda-fx-paper-trading", "Metals": "alpaca-metals-paper-trading",
    "International": "saxo-international-paper-trading",
}


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def age(value, now):
    observed = timestamp(value)
    return (now - observed).total_seconds() if observed else None


def fresh(value, now, maximum=MAX_AGE_SECONDS):
    seconds = age(value, now)
    return seconds is not None and -5 <= seconds <= maximum


def read_json(path):
    try:
        result = json.loads(Path(path).read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def read_accounting(path):
    """A read-only URI refuses to create an empty database on the app host."""
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM pillar_accounting_snapshot")]
    except sqlite3.Error:
        return []


def normalize_accounting(rows, *, now=None):
    now = now or datetime.now(UTC)
    groups = {}
    for raw in rows:
        name = ALIASES.get(str(raw.get("pillar")), str(raw.get("pillar")))
        groups.setdefault(name, []).append(raw)
    result = []
    for name in PILLARS:
        matches = groups.get(name, [])
        raw = matches[0] if len(matches) == 1 else {}
        observed = raw.get("provider_timestamp") or raw.get("observed_at")
        reason = None
        if len(matches) != 1:
            reason = "MISSING_OR_DUPLICATE_PILLAR"
        elif not fresh(observed, now):
            reason = "STALE_OR_INVALID_TIMESTAMP"
        elif raw.get("provider_observed") not in (True, 1):
            reason = "PROVIDER_NOT_OBSERVED"
        elif finite(raw.get("allocation_cap")) != 1000.0:
            reason = "CAPITAL_POLICY_MISMATCH"
        elif raw.get("accounting_status") != "ACCOUNTING_VERIFIED":
            reason = "ACCOUNTING_UNVERIFIED"
        source = {key: finite(raw.get(field)) for key, field in FIELDS.items()}
        if reason is None and source["equity"] is not None:
            capital_parts = [source[k] for k in ("deployed", "available", "pending")]
            if all(v is not None for v in capital_parts) and abs(source["equity"] - sum(capital_parts)) > 0.02:
                reason = "CAPITAL_IDENTITY_MISMATCH"
        result.append({
            "pillar": name, "authorized_capital": 1000.0, "observed_at": observed,
            "age_seconds": age(observed, now), "status": reason or "VERIFIED",
            **{key: value if reason is None else None for key, value in source.items()},
            "reported_values": source,
        })
    totals = {}
    for key in FIELDS:
        values = [row[key] for row in result]
        totals[key] = sum(values) if all(v is not None for v in values) else None
    complete = all(row["status"] == "VERIFIED" for row in result)
    times = [timestamp(row["observed_at"]) for row in result]
    return {
        "schema_version": REPORT_VERSION, "capital_policy": POLICY_VERSION,
        "status": "AVAILABLE" if complete and all(totals[k] is not None for k in ("equity", "deployed", "available")) else "PARTIAL",
        "authorized_capital": 6000.0,
        "observed_at": min(times).isoformat() if all(t is not None for t in times) else None,
        "checked_at": now.isoformat(), **totals, "pillars": result,
        "realized_scope": "ledger reported realized today; fee completeness not established",
        "net_income": None, "income_status": "COST_COMPLETE_FORWARD_OUTCOMES_REQUIRED",
        "trades_today": None,
        "trades_today_reason": "filled legs and completed round trips are not interchangeable",
    }


def runtime_view(runtime, external, *, now):
    heartbeat = runtime.get("last_heartbeat_at") or external.get("generated_at_utc")
    current = fresh(heartbeat, now)
    live = runtime.get("live_trading_enabled", external.get("live_trading_enabled"))
    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    public = external.get("six_pillars") if isinstance(external.get("six_pillars"), dict) else {}
    result = {}
    for pillar in PILLARS:
        names = ("kalshi_predictions", "kalshi_perps") if pillar == "Kalshi" else (pillar.lower(),)
        records = [public[n] for n in names if isinstance(public.get(n), dict)]
        job = jobs.get(JOBS.get(pillar), {})
        if job:
            records = [{"enabled": not job.get("disabled", False), "last_activity_at": job.get("last_finished_at"), "last_error": job.get("last_error")}]
        observed = [r.get("last_activity_at") for r in records]
        enabled = bool(records) and all(r.get("enabled") is True for r in records)
        active = current and enabled and all(fresh(t, now, 900) for t in observed)
        errors = ["RUNTIME_OR_PROVIDER_REJECTION" for r in records if r.get("last_error")]
        state = "STALE / UNKNOWN" if not current else "SCANNING / NO EXECUTION PROOF" if active else "DISABLED / NO RECENT CYCLE"
        if active and errors:
            state = "ACTIVE / BLOCKED OR DEGRADED"
        result[pillar] = {"state": state, "active": active, "last_activity_at": observed, "reasons": errors}
    return {"heartbeat_at": heartbeat, "heartbeat_fresh": current, "live_trading_enabled": live,
            "healthy": current and live is False and runtime.get("healthy", external.get("runtime_health")) is True,
            "pillars": result}


def write_position_observations(root, rows, states, *, now):
    """Export only display fields; do not assert stronger ownership than evidence."""
    clean = []
    for row in rows:
        name = ALIASES.get(str(row.get("pillar")), str(row.get("pillar")))
        state = states.get(row.get("pillar"), {})
        clean.append({"pillar": name, "symbol": str(row.get("symbol") or ""),
            "provider": str(row.get("broker") or ""),
            "quantity": finite(row.get("quantity")), "average_price": finite(row.get("average_price")),
            "current_price": finite(row.get("current_price")), "market_value": finite(row.get("market_value")),
            "unrealized_pnl": finite(row.get("unrealized_pnl")),
            "margin_committed": finite(row.get("margin_committed")),
            "classification": str(row.get("classification") or "UNKNOWN"),
            "ownership": "NOT_PROVEN_BY_THIS_REPORT", "observed_at": state.get("observed_at"),
            "valuation_currency": row.get("currency") or ("USD" if "Alpaca" in str(row.get("broker")) else "UNVERIFIED"),
        })
    payload = {"observed_at": now.isoformat(), "scope": "provider observations; not clean forward-test results", "positions": clean}
    destination = Path(root) / "var/runtime/position_observations.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(destination)


def build_report(root, *, now=None):
    root = Path(root)
    now = now or datetime.now(UTC)
    report = normalize_accounting(read_accounting(root / "var/autotrader/portfolio.db"), now=now)
    runtime = read_json(root / "var/autotrader/status.json")
    external = read_json(root / "var/runtime/external_status.json")
    report["runtime"] = runtime_view(runtime, external, now=now)
    positions = read_json(root / "var/runtime/position_observations.json")
    report["position_observations"] = positions.get("positions", [])
    report["positions_observed_at"] = positions.get("observed_at")
    report["positions_fresh"] = fresh(positions.get("observed_at"), now)
    report["first_qualifying_post_boundary_trade"] = external.get("first_qualifying_post_boundary_trade")
    report["source"] = "read-only runtime accounting ledger"
    report["capital_state_diagnostics"] = capital_diagnostics(root, now=now)
    report["execution_evidence"] = cycle_evidence(root, now=now)
    return report
