"""Durable, paper-only research and experiment accounting primitives.

This module deliberately has no broker imports and cannot submit orders.  It is
the persistence boundary for external research, shadow hedges, features,
regimes, cash buckets, daily reports, and future live-readiness evidence.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_records (
 research_id TEXT PRIMARY KEY, lane TEXT NOT NULL, source TEXT NOT NULL,
 source_url TEXT, source_type TEXT, as_of_date TEXT, retrieved_at TEXT NOT NULL,
 freshness TEXT, instrument TEXT, signal_type TEXT, signal_value REAL,
 confidence REAL, metadata_json TEXT NOT NULL, backtest_status TEXT,
 walk_forward_status TEXT, paper_shadow_status TEXT, promotion_status TEXT,
 model_weight REAL NOT NULL DEFAULT 0, broker_control INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS research_features (
 id INTEGER PRIMARY KEY AUTOINCREMENT, feature_name TEXT NOT NULL,
 feature_value REAL, source TEXT, recorded_at TEXT NOT NULL, freshness TEXT,
 experiment_id TEXT, symbol TEXT, pillar TEXT);
CREATE TABLE IF NOT EXISTS regimes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT NOT NULL, evidence_json TEXT,
 recorded_at TEXT NOT NULL, experiment_id TEXT);
CREATE TABLE IF NOT EXISTS hedge_observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, candidate TEXT, instrument TEXT,
 mode TEXT NOT NULL, reason TEXT, score REAL, recommended_size REAL,
 risk_before REAL, risk_after REAL, simulated_result REAL, effectiveness REAL,
 recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cash_buckets (
 experiment_id TEXT PRIMARY KEY, starting_capital REAL NOT NULL,
 capital_deployed REAL NOT NULL, gross_realized_profit REAL NOT NULL,
 fees_costs REAL NOT NULL, net_realized_cash REAL NOT NULL,
 liquid_realized_cash REAL NOT NULL, harvested_cash REAL NOT NULL,
 redeployable_cash REAL NOT NULL, unrealized_pnl REAL NOT NULL,
 theoretical_compounded_equity REAL NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_reports (
 report_date TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS readiness (
 experiment_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class ResearchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def put_research(self, record: Mapping[str, Any]) -> None:
        fields = ("research_id", "lane", "source", "source_url", "source_type", "as_of_date", "retrieved_at", "freshness", "instrument", "signal_type", "signal_value", "confidence", "metadata_json", "backtest_status", "walk_forward_status", "paper_shadow_status", "promotion_status", "model_weight", "broker_control")
        values = dict(record)
        values.setdefault("retrieved_at", utc_now())
        values["metadata_json"] = _json(values.get("metadata_json", {})) if not isinstance(values.get("metadata_json"), str) else values["metadata_json"]
        values["broker_control"] = 0
        with self.connection() as conn:
            conn.execute(f"INSERT OR REPLACE INTO research_records ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", [values.get(f) for f in fields])

    def research(self, lane: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM research_records" + (" WHERE lane=?" if lane else "") + " ORDER BY retrieved_at DESC", ([lane] if lane else [])).fetchall()
        return [dict(row) for row in rows]

    def put_feature(self, *, name: str, value: float, source: str, experiment_id: str, symbol: str, pillar: str, freshness: str = "FRESH") -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO research_features(feature_name,feature_value,source,recorded_at,freshness,experiment_id,symbol,pillar) VALUES(?,?,?,?,?,?,?,?)", (name, value, source, utc_now(), freshness, experiment_id, symbol, pillar))

    def put_regime(self, regime: str, evidence: Mapping[str, Any], experiment_id: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO regimes(regime,evidence_json,recorded_at,experiment_id) VALUES(?,?,?,?)", (regime, _json(evidence), utc_now(), experiment_id))

    def put_hedge(self, observation: Mapping[str, Any]) -> None:
        fields = ("candidate", "instrument", "mode", "reason", "score", "recommended_size", "risk_before", "risk_after", "simulated_result", "effectiveness")
        with self.connection() as conn:
            conn.execute(f"INSERT INTO hedge_observations ({','.join(fields)},recorded_at) VALUES ({','.join('?' for _ in fields)},?)", [observation.get(f) for f in fields] + [utc_now()])

    def put_cash(self, experiment_id: str, **values: float) -> None:
        names = ("starting_capital", "capital_deployed", "gross_realized_profit", "fees_costs", "net_realized_cash", "liquid_realized_cash", "harvested_cash", "redeployable_cash", "unrealized_pnl", "theoretical_compounded_equity")
        payload = {name: float(values.get(name, 0.0)) for name in names}
        payload["starting_capital"] = float(values.get("starting_capital", 5000.0))
        payload["theoretical_compounded_equity"] = payload["starting_capital"] + payload["net_realized_cash"]
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO cash_buckets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (experiment_id, *[payload[n] for n in names], utc_now()))

    def put_report(self, report_date: date | str, payload: Mapping[str, Any]) -> None:
        day = report_date.isoformat() if isinstance(report_date, date) else str(report_date)
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO daily_reports VALUES (?,?,?)", (day, _json(payload), utc_now()))

    def put_readiness(self, experiment_id: str, payload: Mapping[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO readiness VALUES (?,?,?)", (experiment_id, _json(payload), utc_now()))


def classify_readiness(*, paper_days: int, completed_trades: int, expectancy: float, profit_factor: float | None, drawdown: float, execution_failures: int, reconciliation_failures: int, model_stability: bool, broker_reliability: bool) -> str:
    if execution_failures or reconciliation_failures or not broker_reliability:
        return "NOT_READY"
    if paper_days < 30 or completed_trades < 100 or expectancy <= 0 or (profit_factor is not None and profit_factor <= 1) or drawdown > 0.15 or not model_stability:
        return "COLLECTING_EVIDENCE"
    return "PAPER_VALIDATED"


def compounding_decision(*, expectancy: float, drawdown: float, volatility: float, sample_size: int, capital_efficiency: float, confidence: float) -> str:
    if sample_size < 30 or drawdown > 0.10 or confidence < 0.60:
        return "RETAIN"
    if expectancy > 0 and capital_efficiency > 0 and volatility < 0.05:
        return "REDEPLOY"
    return "HARVEST"
