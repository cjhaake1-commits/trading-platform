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
from math import sqrt

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
CREATE TABLE IF NOT EXISTS provider_status (
 lane TEXT PRIMARY KEY, status TEXT NOT NULL, last_success TEXT, last_attempt TEXT NOT NULL,
 next_refresh TEXT, records_ingested INTEGER NOT NULL DEFAULT 0, records_updated INTEGER NOT NULL DEFAULT 0,
 records_skipped INTEGER NOT NULL DEFAULT 0, last_error TEXT);
CREATE TABLE IF NOT EXISTS feature_attribution (
 id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id TEXT NOT NULL, feature_name TEXT NOT NULL,
 feature_value REAL, feature_source TEXT, feature_freshness TEXT, feature_weight REAL,
 regime TEXT, model TEXT, decision TEXT, outcome TEXT, realized_contribution REAL,
 confidence REAL, recorded_at TEXT NOT NULL);
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

    def put_provider_status(self, lane: str, *, status: str, records_ingested: int = 0, last_error: str | None = None, next_refresh: str | None = None) -> None:
        now = utc_now()
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO provider_status(lane,status,last_success,last_attempt,next_refresh,records_ingested,last_error) VALUES(?,?,?,?,?,?,?)", (lane, status, now if status == "CONNECTED" else None, now, next_refresh, records_ingested, last_error))

    def provider_status(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM provider_status ORDER BY lane").fetchall()]

    def put_attribution(self, *, observation_id: str, feature_name: str, feature_value: float, feature_source: str, feature_freshness: str, feature_weight: float, regime: str, model: str, decision: str, outcome: str | None = None, realized_contribution: float | None = None, confidence: float = 0.0) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO feature_attribution(observation_id,feature_name,feature_value,feature_source,feature_freshness,feature_weight,regime,model,decision,outcome,realized_contribution,confidence,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (observation_id, feature_name, feature_value, feature_source, feature_freshness, feature_weight, regime, model, decision, outcome, realized_contribution, confidence, utc_now()))


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


def performance_metrics(closes: list[float], *, periods_per_year: int = 252) -> dict[str, float | None]:
    """Calculate deterministic research metrics from an ordered close series."""
    if len(closes) < 2 or any(value <= 0 for value in closes):
        return {"return_1m": None, "return_3m": None, "return_6m": None, "return_1y": None, "return_3y": None, "return_5y": None, "volatility": None, "max_drawdown": None, "risk_adjusted_return": None, "trend_persistence": None}
    def ret(days: int) -> float | None:
        return closes[-1] / closes[-days - 1] - 1 if len(closes) > days else None
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
    volatility = sqrt(variance) * sqrt(periods_per_year)
    peak = closes[0]
    drawdowns = []
    for value in closes:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1)
    persistence = sum(1 for value in returns if value > 0) / len(returns)
    return {"return_1m": ret(21), "return_3m": ret(63), "return_6m": ret(126), "return_1y": ret(252), "return_3y": ret(756), "return_5y": ret(1260), "volatility": volatility, "max_drawdown": min(drawdowns), "risk_adjusted_return": (mean_return / volatility * sqrt(periods_per_year)) if volatility else None, "trend_persistence": persistence}


def normalize_disclosure(*, lane: str, source: str, source_url: str, as_of_date: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize delayed public disclosures into research-only records."""
    research_id = f"{lane}:{source}:{as_of_date}:{payload.get('symbol') or payload.get('asset') or payload.get('title') or 'record'}"
    return {"research_id": research_id, "lane": lane, "source": source, "source_url": source_url, "source_type": "public_disclosure", "as_of_date": as_of_date, "freshness": "DELAYED", "instrument": payload.get("symbol") or payload.get("asset"), "signal_type": payload.get("signal_type", "structural"), "signal_value": payload.get("signal_value"), "confidence": float(payload.get("confidence", 0.0) or 0.0), "metadata_json": dict(payload), "backtest_status": payload.get("backtest_status", "NOT_STARTED"), "walk_forward_status": payload.get("walk_forward_status", "NOT_STARTED"), "paper_shadow_status": payload.get("paper_shadow_status", "NOT_STARTED"), "promotion_status": payload.get("promotion_status", "RESEARCH"), "model_weight": 0.0, "broker_control": 0}


def classify_regime(*, return_pct: float, volatility: float, trend_strength: float, gap_pct: float = 0.0, liquidity_score: float = 1.0) -> str:
    if liquidity_score < 0.25:
        return "liquidity_constrained"
    if abs(gap_pct) >= 0.04:
        return "event_gap"
    if volatility >= 0.04:
        return "high_volatility"
    if volatility <= 0.01:
        return "low_volatility"
    if trend_strength >= 0.6:
        return "risk_on" if return_pct >= 0 else "risk_off"
    return "trending" if abs(return_pct) >= 0.02 else "mean_reverting"


def evaluate_shadow_hedge(*, overnight_direction: float, gap_pct: float, volatility: float, portfolio_concentration: float, mode: str = "SHADOW_ONLY") -> dict[str, Any]:
    score = min(1.0, abs(gap_pct) * 8 + volatility * 4 + portfolio_concentration * 0.5)
    candidate = score >= 0.5
    return {"candidate": candidate, "instrument": "INDEX_FUTURE_RESEARCH", "mode": mode if mode in {"EXECUTABLE_SIM", "SHADOW_ONLY"} else "SHADOW_ONLY", "reason": "opening risk concentration" if candidate else "opening risk below threshold", "score": score, "recommended_size": round(score * 0.10, 6), "risk_before": portfolio_concentration, "risk_after": max(0.0, portfolio_concentration - score * 0.10), "simulated_result": None, "effectiveness": None}


def apply_v2_exit(store: ResearchStore, *, experiment_id: str, trade_id: str, entry_value: float, exit_value: float, fees: float = 0.0, capital_deployed: float = 0.0, unrealized_pnl: float = 0.0) -> dict[str, float]:
    """Idempotent-friendly cash calculation for a broker-confirmed v2 exit."""
    gross = float(exit_value) - float(entry_value)
    net = gross - float(fees)
    store.put_cash(experiment_id, starting_capital=5000.0, capital_deployed=capital_deployed, gross_realized_profit=gross, fees_costs=fees, net_realized_cash=net, liquid_realized_cash=max(net, 0.0), redeployable_cash=max(net, 0.0), unrealized_pnl=unrealized_pnl)
    return {"trade_id": trade_id, "gross_realized_profit": gross, "fees_costs": float(fees), "net_realized_cash": net}


def build_daily_report(*, report_date: str, starting_equity: float, ending_equity: float, realized_cash: float, liquid_cash: float, redeployable_cash: float, harvested_cash: float, unrealized_pnl: float, trades: int, wins: int, expectancy: float, profit_factor: float | None, drawdown: float, capital_utilization: float, pillar_attribution: Mapping[str, float] | None = None, **extra: Any) -> dict[str, Any]:
    return {"date": report_date, "starting_equity": starting_equity, "ending_equity": ending_equity, "realized_cash": realized_cash, "liquid_cash": liquid_cash, "redeployable_cash": redeployable_cash, "harvested_cash": harvested_cash, "unrealized_pnl": unrealized_pnl, "daily_return": (ending_equity / starting_equity - 1) if starting_equity else 0.0, "trades": trades, "win_rate": (wins / trades) if trades else 0.0, "expectancy": expectancy, "profit_factor": profit_factor, "drawdown": drawdown, "capital_utilization": capital_utilization, "pillar_attribution": dict(pillar_attribution or {}), **extra}
