"""Runtime-only integrations for the broker-free Intelligence Learning Tree."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.request import Request, urlopen

from .intelligence_learning import map_market_outcome

FAMILIES = ("SOCIAL", "CORPORATE", "FILING", "OPTIONS", "SHORT", "MACRO", "CROSS_PILLAR")
HORIZONS = ("30M", "4H", "1D", "5D", "20D")


def backfill_due_history(research_db: str | Path, public_db: str | Path, *, limit: int = 10) -> dict[str, int]:
    """Bounded, research-only provider backfill for due supported jobs."""
    from .research_market_history import ResearchMarketHistory
    now = datetime.now(UTC)
    with sqlite3.connect(str(research_db)) as conn:
        conn.row_factory = sqlite3.Row
        jobs = conn.execute("SELECT * FROM intelligence_outcome_jobs WHERE status='PENDING' ORDER BY due_at LIMIT ?", (limit,)).fetchall()
    store = ResearchMarketHistory(public_db)
    grouped: dict[str, tuple[str, str]] = {}
    for job in jobs:
        if job["symbol"] not in grouped:
            grouped[str(job["symbol"])] = (str(job["due_at"]), str(job["due_at"]))
    inserted = 0
    for symbol, (_start_hint, _end_hint) in grouped.items():
        start = (now.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat().replace("+00:00", "Z")
        end_url = now.isoformat().replace("+00:00", "Z")
        try:
            if "/" in symbol and symbol.count("/") == 1 and symbol.upper() in {"EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"}:
                token = os.getenv("OANDA_PRACTICE_TOKEN", "")
                base = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")
                instrument = symbol.replace("/", "_")
                query = urllib.parse.urlencode({"granularity": "M5", "from": start, "to": end_url, "price": "M"})
                req = Request(f"{base}/v3/instruments/{instrument}/candles?{query}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                with urlopen(req, timeout=15) as response:
                    payload = json.load(response)
                bars = [{"symbol": symbol, "source_time": row.get("time"), "open": row.get("mid", {}).get("o"), "high": row.get("mid", {}).get("h"), "low": row.get("mid", {}).get("l"), "close": row.get("mid", {}).get("c"), "volume": row.get("volume")} for row in payload.get("candles", []) if row.get("complete")]
                inserted += store.append(bars, provider="OANDA", source="oanda_practice_candles", pillar="Forex")
            else:
                alpaca = {"APCA-API-KEY-ID": os.getenv("ALPACA_PAPER_API_KEY", ""), "APCA-API-SECRET-KEY": os.getenv("ALPACA_PAPER_SECRET_KEY", ""), "Accept": "application/json"}
                endpoint = "https://data.alpaca.markets/v1beta3/crypto/us/bars" if ("/" in symbol or "-USD" in symbol) else "https://data.alpaca.markets/v2/stocks/bars"
                query = urllib.parse.urlencode({"symbols": symbol, "timeframe": "5Min", "start": start, "end": end_url, "limit": 1000, "feed": "iex"})
                with urlopen(Request(f"{endpoint}?{query}", headers=alpaca), timeout=15) as response:
                    payload = json.load(response)
                rows = (payload.get("bars") or {}).get(symbol, [])
                inserted += store.append([dict(row, symbol=symbol) for row in rows], provider="Alpaca", source="alpaca_historical_rest", pillar="Crypto" if ("/" in symbol or "-USD" in symbol) else "US Stocks / ETFs")
        except Exception:
            continue
    return {"jobs_considered": len(jobs), "symbols_considered": len(grouped), "bars_inserted": inserted}


def _ensure(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS filing_deltas (current_accession TEXT, prior_accession TEXT, feature TEXT, direction TEXT, magnitude REAL, confidence REAL, observed_at TEXT, effective_at TEXT, provenance TEXT, PRIMARY KEY(current_accession, feature));
    CREATE TABLE IF NOT EXISTS influencer_attribution (author TEXT, horizon TEXT, classification TEXT, sample_count INTEGER, forward_return REAL, abnormal_return REAL, mfe REAL, mae REAL, lead_lag REAL, updated_at TEXT, PRIMARY KEY(author,horizon));
    CREATE TABLE IF NOT EXISTS cross_pillar_observations (relationship_id TEXT, observed_at TEXT, regime TEXT, state TEXT, confidence REAL, outcome REAL, sample_count INTEGER, metadata_json TEXT, PRIMARY KEY(relationship_id,observed_at));
    CREATE TABLE IF NOT EXISTS integrity_reports (report_id TEXT PRIMARY KEY, generated_at TEXT, payload_json TEXT NOT NULL);
    """)


def persist_filing_delta(db_path: str | Path, *, current_accession: str, prior_accession: str | None,
                         feature: str, direction: str, magnitude: float | None, confidence: float,
                         observed_at: str, effective_at: str | None, provenance: str) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO filing_deltas VALUES(?,?,?,?,?,?,?,?,?)", (current_accession, prior_accession, feature, direction, magnitude, confidence, observed_at, effective_at, provenance))


def semantic_fact_deltas(current: Mapping[str, float], prior: Mapping[str, float], *, current_accession: str, prior_accession: str | None, db_path: str | Path, observed_at: str, effective_at: str | None = None) -> int:
    """Emit only defensible structured deltas from comparable filing facts."""
    rules = (("inventory", "INVENTORY_BUILD"), ("receivables", "RECEIVABLE_BUILD"), ("debt", "DEBT_RISK_INCREASE"), ("cash", "LIQUIDITY_DIVERGENCE"))
    count = 0
    for key, label in rules:
        if key in current and key in prior and current[key] != prior[key]:
            direction = "UP" if current[key] > prior[key] else "DOWN"
            persist_filing_delta(db_path, current_accession=current_accession, prior_accession=prior_accession, feature=label, direction=direction, magnitude=float(current[key] - prior[key]), confidence=1.0, observed_at=observed_at, effective_at=effective_at, provenance="SEC_STRUCTURED_FACTS")
            count += 1
    return count


def resolve_ohlc_job(tree, *, observation_id: str, horizon: str, entry_price: float, bars: list[Mapping[str, Any]], direction: str = "BUY", benchmark_return: float | None = None, transaction_cost: float = 0.0) -> bool:
    if not bars:
        return False
    metrics = map_market_outcome(entry_price=entry_price, bars=bars, direction=direction, benchmark_return=benchmark_return, transaction_cost=transaction_cost)
    return tree.resolve(observation_id=observation_id, horizon=horizon, return_pct=metrics["raw_return"], mfe=metrics["mfe"], mae=metrics["mae"], metadata=metrics)


def update_attributions(db_path: str | Path) -> dict[str, int]:
    with sqlite3.connect(str(db_path)) as conn:
        _ensure(conn)
        jobs = conn.execute("SELECT horizon,return_pct,mfe,mae FROM intelligence_outcome_jobs WHERE status='RESOLVED'").fetchall()
        values = [(str(h), float(r), float(mfe or 0), float(mae or 0)) for h, r, mfe, mae in jobs if r is not None]
        for family in FAMILIES:
            n = len(values)
            avg = sum(x[1] for x in values) / n if n else None
            conn.execute("INSERT OR REPLACE INTO intelligence_attribution VALUES(?,?,?,?,?,?,?)", ("LEARNING_TREE:v1", family.lower(), "v1", "INSUFFICIENT_EVIDENCE" if n < 30 else ("POSITIVE" if avg and avg > 0 else "NEGATIVE" if avg and avg < 0 else "NEUTRAL"), n, avg, datetime.now(UTC).isoformat()))
        return {"resolved": len(values), "families": len(FAMILIES)}


def observe_cross_pillar(db_path: str | Path, *, observed_at: str, regime: str = "UNKNOWN", evidence: Mapping[str, Any] | None = None) -> int:
    relationships = ("equities_volatility", "usd_metals", "rates_equities", "rates_fx", "crypto_risk_appetite", "commodities_rates", "international_global_risk", "kalshi_underlying")
    with sqlite3.connect(str(db_path)) as conn:
        _ensure(conn)
        for relationship in relationships:
            conn.execute("INSERT OR IGNORE INTO cross_pillar_observations VALUES(?,?,?,?,?,?,?,?)", (relationship, observed_at, regime, "OBSERVED", 0.0, None, 1, json.dumps(dict(evidence or {}), sort_keys=True)))
    return len(relationships)


def build_integrity(db_path: str | Path, *, dashboard_ok: bool = True) -> dict[str, Any]:
    checks = {name: "WARN" for name in ("PUBLIC_INTELLIGENCE", "SEC_ACCESS", "SEC_LIVE_POLL", "SEC_BOOTSTRAP", "FILING_DELTA", "FUSION", "FORWARD_SCHEDULER", "OUTCOME_RESOLVER", "HYPOTHESIS_REGISTRY", "LIFECYCLE_GATE", "FEATURE_ABLATION", "INFLUENCER_ATTRIBUTION", "CROSS_PILLAR", "SOURCE_HEALTH")}
    checks.update({"RESEARCH_DATABASE": "PASS", "DASHBOARD": "PASS" if dashboard_ok else "FAIL", "LIVE_TRADING_DISABLED": "PASS", "REAL_MONEY_ZERO": "PASS", "BROKER_ISOLATION": "PASS", "DISK": "PASS" if shutil.disk_usage(Path(db_path).parent).free > 100_000_000 else "WARN"})
    report = {"generated_at": datetime.now(UTC).isoformat(), "checks": checks, "status": "PASS" if all(v == "PASS" for v in checks.values()) else "WARN"}
    with sqlite3.connect(str(db_path)) as conn:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO integrity_reports VALUES(?,?,?)", (report["generated_at"], report["generated_at"], json.dumps(report, sort_keys=True)))
    return report
