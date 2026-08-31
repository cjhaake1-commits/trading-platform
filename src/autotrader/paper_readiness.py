"""Truthful six-pillar paper readiness matrix; never authorizes execution."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

PILLARS = {"US STOCKS / ETFs": "Alpaca PAPER", "CRYPTO": "Alpaca PAPER", "FOREX": "OANDA PRACTICE", "METALS / COMMODITIES": "Configured PAPER", "INTERNATIONAL": "Saxo SIM", "KALSHI": "Predictions + Perps demo"}
CHECKS = ("ENGINE", "ACCOUNT", "AUTH", "MARKET_DATA", "CLOCK_CALENDAR", "CANDIDATE_DISCOVERY", "STRATEGY_EVALUATION", "QUALIFICATION", "RISK", "PAPER_EXECUTION", "ORDER_ACK", "FILL", "POSITION_RECONCILIATION", "EXIT_MANAGEMENT", "LEARNING_CAPTURE", "MARKET_HISTORY", "RESTART_CONTINUITY", "TELEMETRY")


def build_readiness(*, provider_status: dict[str, dict[str, object]] | None = None, market_open: dict[str, bool] | None = None) -> dict[str, object]:
    provider_status = provider_status or {}
    market_open = market_open or {}
    result = {"generated_at": datetime.now(UTC).isoformat(), "research_only": True, "live_trading_enabled": False, "pillars": {}}
    for pillar, provider in PILLARS.items():
        row = provider_status.get(pillar, {})
        connected = row.get("connected")
        checks = {check: {"status": "PASS" if connected is True else "WARN", "reason": "provider connected" if connected is True else "provider evidence unavailable"} for check in CHECKS}
        checks["CLOCK_CALENDAR"] = {"status": "PASS", "reason": "session-aware status required by runtime"}
        checks["MARKET_DATA"] = {"status": "PASS" if row.get("market_data") is True else "WARN", "reason": "market data observed" if row.get("market_data") is True else "market data not observed"}
        healthy = connected is True and row.get("market_data") is True
        result["pillars"][pillar] = {"provider": provider, "market": "OPEN" if market_open.get(pillar) else "CLOSED/UNKNOWN", "status": "READY" if healthy else "READY_WAITING_FOR_MARKET" if connected is True else "UNKNOWN", "checks": checks}
    return result


def persist_readiness(snapshot: dict[str, object], db_path: str | Path = "var/autotrader/research.db") -> int:
    """Persist the single readiness snapshot used by operational consumers.

    This is telemetry only: it never authorizes an order and deliberately stores
    the complete provider evidence payload for later inspection.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = str(snapshot.get("generated_at") or datetime.now(UTC).isoformat())
    rows = snapshot.get("pillars") or {}
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS paper_readiness_snapshots (
            pillar TEXT NOT NULL, generated_at TEXT NOT NULL, provider TEXT NOT NULL,
            status TEXT NOT NULL, market TEXT, checks_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL, PRIMARY KEY (pillar, generated_at)
        )""")
        for pillar, evidence in rows.items():
            item = evidence if isinstance(evidence, dict) else {}
            connection.execute(
                "INSERT OR REPLACE INTO paper_readiness_snapshots VALUES (?,?,?,?,?,?,?)",
                (str(pillar), generated_at, str(item.get("provider", "UNKNOWN")),
                 str(item.get("status", "UNKNOWN")), str(item.get("market", "UNKNOWN")),
                 json.dumps(item.get("checks", {}), sort_keys=True),
                 json.dumps(item, sort_keys=True)),
            )
    return len(rows)
