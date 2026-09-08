"""Bounded read-only economic diagnostics and native engine order receipts.

Receipts are not independently reconciled fills, owned positions or profit.
This module cannot create a database, modify a ledger or submit orders.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ENGINES = (
    "autonomous-paper-trading", "oanda-fx-paper-trading",
    "alpaca-metals-paper-trading", "saxo-international-paper-trading",
)


def _rows(path, query, parameters=()):
    deadline = time.monotonic() + 3
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            return [dict(row) for row in db.execute(query, parameters)]
    except sqlite3.Error:
        return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _count(value):
    return len(value) if isinstance(value, list) else None


def capital_diagnostics(root, *, now=None):
    now = now or datetime.now(UTC)
    db = Path(root) / "var/autotrader/portfolio.db"
    state = _rows(db, "SELECT equity,cash,daily_pnl,weekly_pnl,peak_equity,updated_at FROM portfolio_state WHERE id=1")
    baselines = _rows(db, "SELECT pillar,equity_date,starting_economic_equity,source,persisted_at FROM pillar_day_start_equity WHERE equity_date=? ORDER BY pillar", (now.date().isoformat(),))
    return {"scope": "persisted state diagnostics, not provider balances or earned income",
            "portfolio_state": state, "day_start_baselines": baselines}


def cycle_evidence(root, *, now=None, per_engine_limit=2000):
    """Deduplicate reported provider order IDs in a bounded current-UTC-day read."""
    now = now or datetime.now(UTC)
    path = Path(root) / "var/autotrader/lifecycle.db"
    latest = []
    receipts = {}
    complete = True
    failures = []
    for engine in ENGINES:
        rows = _rows(path,
            "SELECT cycle_id,started_at,finished_at,provider_status,payload_json FROM engine_cycles "
            "WHERE cycle_id GLOB ? ORDER BY cycle_id DESC LIMIT ?",
            (f"{engine}:{now.date().isoformat()}*", per_engine_limit + 1))
        if rows is None:
            failures.append(engine)
            complete = False
            continue
        if len(rows) > per_engine_limit:
            complete = False
        for index, row in enumerate(rows[:per_engine_limit]):
            try:
                data = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                complete = False
                continue
            if not isinstance(data, dict):
                complete = False
                continue
            if any(data.get(flag) is True for flag in ("is_test", "synthetic", "replayed", "historical")):
                continue
            if index == 0:
                latest.append({"engine": engine, "observed_at": row["finished_at"],
                    "cycle_result": row["provider_status"],
                    "qualified_signals": _number(data.get("qualified_signals")),
                    "crypto_qualified": _number(data.get("crypto_qualified")),
                    "equity_qualified": _number(data.get("equity_qualified")),
                    "forex_qualified": _number(data.get("forex_qualified")),
                    "qualified": _number(data.get("qualified")),
                    "submitted": data.get("submitted") is True,
                    "risk_rejection_count": _count(data.get("risk_rejections")),
                    "submission_failure_count": _count(data.get("submission_failures")),
                    "duplicate_count": _count(data.get("duplicates"))})
            entries = data.get("entries") if isinstance(data.get("entries"), list) else []
            if data.get("order_id") and (data.get("submitted") is True or data.get("execution_state") == "ACTIVE — DEPLOYING CAPITAL"):
                entries = [*entries, {"broker_order_id": data["order_id"], "symbol": data.get("candidate"), "pillar": data.get("pillar")}]
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("broker_order_id"):
                    continue
                if any(entry.get(flag) is True for flag in ("is_test", "synthetic", "replayed", "historical")):
                    continue
                identifier = str(entry["broker_order_id"])
                key = (str(entry.get("broker") or engine), identifier)
                receipts.setdefault(key, {"engine": engine, "pillar": entry.get("pillar"),
                    "instrument": entry.get("symbol"), "provider_order_id": identifier,
                    "observed_at": row["finished_at"], "cycle_started_at": row["started_at"],
                    "quantity_reported": _number(entry.get("quantity", entry.get("units"))),
                    "evidence_stage": "ENGINE_REPORTED_PROVIDER_ORDER_RECEIPT",
                    "platform_owned": None, "fill_confirmed": None,
                    "clean_forward_qualified": None})
    ordered = sorted(receipts.values(), key=lambda row: str(row["observed_at"]), reverse=True)
    return {"scope": "current UTC day engine receipts; not reconciled fills or income",
            "utc_date": now.date().isoformat(), "window_complete": complete,
            "unreadable_engines": failures, "latest_cycles": latest,
            "provider_order_receipts_count": len(receipts) if complete else None,
            "observed_receipts_count": len(receipts), "receipts": ordered[:100],
            "net_realized_income": None,
            "net_income_reason": "Cost-complete reconciled ownership and outcomes are required"}
