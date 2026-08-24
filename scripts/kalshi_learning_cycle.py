#!/usr/bin/env python3
"""Derive durable research features from stored Kalshi observations.

This process never calls a provider and never controls a broker. It is safe to
run repeatedly: feature and sample identifiers are content-addressed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from autotrader.kalshi.storage import KalshiResearchStore

HORIZONS = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400}
NUMERIC = {
    "yes_bid_dollars": "kalshi.implied_probability",
    "yes_ask_dollars": "kalshi.yes_ask",
    "volume_fp": "kalshi.volume",
    "liquidity_dollars": "kalshi.liquidity",
    "last_price_dollars": "kalshi.price",
}

def _id(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()

def _num(value: object) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def _time(row: sqlite3.Row) -> float:
    return datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00")).timestamp()

def run_once() -> dict[str, int | float | str]:
    db_path = os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    KalshiResearchStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM kalshi_observations ORDER BY retrieved_at, id").fetchall()
        observations = [r for r in rows if r["observation_type"] == "market" and r["instrument"]]
        conn.execute("BEGIN")
        series: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in observations:
            series.setdefault((row["family"], row["instrument"]), []).append(row)
        feature_count = 0
        for key, history in series.items():
            family, instrument = key
            history.sort(key=_time)
            for i, row in enumerate(history):
                payload = json.loads(row["payload_json"])
                category = str(payload.get("category") or payload.get("title") or "unknown")[:120]
                exchange = payload.get("exchange_index")
                values: dict[str, float | None] = {}
                if family == "predictions":
                    bid, ask = _num(payload.get("yes_bid_dollars")), _num(payload.get("yes_ask_dollars"))
                    if bid is not None and ask is not None:
                        values["kalshi.implied_probability"] = (bid + ask) / 2
                        values["kalshi.spread"] = ask - bid
                    for source, name in NUMERIC.items():
                        if source in payload and name not in values:
                            values[name] = _num(payload.get(source))
                    if payload.get("expiration_time"):
                        try:
                            expiry = datetime.fromisoformat(str(payload["expiration_time"]).replace("Z", "+00:00"))
                            values["kalshi.time_to_resolution_hours"] = max(0.0, (expiry.timestamp() - _time(row)) / 3600)
                        except ValueError:
                            pass
                else:
                    for source, name in (("last_price_dollars", "kalshi.perps.price"), ("funding_rate", "kalshi.perps.funding"), ("liquidity_dollars", "kalshi.perps.liquidity")):
                        if source in payload:
                            values[name] = _num(payload.get(source))
                previous = history[i - 1] if i else None
                if previous:
                    old = json.loads(previous["payload_json"])
                    if family == "predictions":
                        old_bid, old_ask = _num(old.get("yes_bid_dollars")), _num(old.get("yes_ask_dollars"))
                        now_mid = values.get("kalshi.implied_probability")
                        old_mid = (old_bid + old_ask) / 2 if old_bid is not None and old_ask is not None else None
                        if now_mid is not None and old_mid is not None:
                            values["kalshi.probability_change"] = now_mid - old_mid
                            dt = max(_time(row) - _time(previous), 1.0)
                            values["kalshi.velocity"] = (now_mid - old_mid) / dt
                            values["kalshi.acceleration"] = values["kalshi.velocity"]
                        old_spread = old_ask - old_bid if old_bid is not None and old_ask is not None else None
                        if values.get("kalshi.spread") is not None and old_spread is not None:
                            values["kalshi.spread_change"] = values["kalshi.spread"] - old_spread
                    else:
                        old_price = _num(old.get("last_price_dollars"))
                        price = values.get("kalshi.perps.price")
                        if old_price not in (None, 0) and price is not None:
                            values["kalshi.perps.return"] = price / old_price - 1
                            values["kalshi.perps.momentum"] = values["kalshi.perps.return"]
                for name, value in values.items():
                    conn.execute("INSERT OR REPLACE INTO kalshi_learning_features VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (_id(row["id"], name), family, instrument, name, value, category, str(exchange) if exchange is not None else None,
                         row["id"], row["retrieved_at"], row["quality"], "RESEARCH_ONLY", 0.0, 0, 0))
                    feature_count += 1
        cross_count = 0
        target_rows = conn.execute(
            "SELECT * FROM kalshi_pillar_observations WHERE feature='price' "
            "AND pillar IN ('alpaca_equities','alpaca_crypto','oanda_fx','alpaca_metals','ibkr_global') "
            "ORDER BY observed_at"
        ).fetchall()
        # Every normalized non-Kalshi observation participates in learning as
        # a durable, research-only market feature.  This prevents healthy
        # pillar telemetry from appearing as 0 features while preserving the
        # original value and provenance.
        for target in target_rows:
            conn.execute("INSERT OR IGNORE INTO kalshi_learning_features VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (_id(target["id"], "market.price"), str(target["pillar"]), str(target["symbol"]),
                          "market.price", _num(target["value"]), str(target["pillar"]), None,
                          target["id"], target["observed_at"], target["source_quality"],
                          "RESEARCH_ONLY", 0.0, 0, 0))
            feature_count += 1
        source_features = conn.execute(
            "SELECT * FROM kalshi_learning_features WHERE feature_name IN "
            "('kalshi.implied_probability','kalshi.probability_change','kalshi.perps.return') "
            "ORDER BY observed_at DESC LIMIT 500"
        ).fetchall()
        for source in source_features:
            try:
                source_ts = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            for target in target_rows:
                try:
                    target_ts = datetime.fromisoformat(target["observed_at"].replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if abs(target_ts - source_ts) > 300:
                    continue
                for requested_lag in HORIZONS.values():
                    future = conn.execute(
                        "SELECT value,observed_at FROM kalshi_pillar_observations WHERE pillar=? AND symbol=? "
                        "AND feature='price' AND observed_at>? ORDER BY observed_at LIMIT 1",
                        (target["pillar"], target["symbol"], target["observed_at"]),
                    ).fetchone()
                    if not future or _num(target["value"]) in (None, 0) or _num(future[0]) is None:
                        continue
                    future_ts = datetime.fromisoformat(future[1].replace("Z", "+00:00")).timestamp()
                    actual_lag = int(round(future_ts - source_ts))
                    if abs(actual_lag - requested_lag) > max(60, requested_lag * 0.25):
                        continue
                    response = _num(future[0]) / _num(target["value"]) - 1
                    sid = _id(source["id"], target["pillar"], target["symbol"], target["observed_at"], requested_lag)
                    conn.execute("INSERT OR IGNORE INTO kalshi_cross_market_samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, source["family"], source["instrument"], source["feature_name"], str(target["pillar"]),
                         str(target["symbol"] or "unknown"), requested_lag, source["observed_at"], future[1],
                         response, target["regime"] or "unknown", target["source_quality"],
                         "COLLECTING_EVIDENCE", None, None, 0))
                    cross_count += 1
                    if cross_count >= 5000:
                        break
                if cross_count >= 5000:
                    break
            if cross_count >= 5000:
                break
        resolved = conn.execute("SELECT COUNT(*) FROM kalshi_resolutions WHERE result IN ('yes','no')").fetchone()[0]
        run_id = _id(datetime.now(UTC).isoformat(), len(rows), feature_count)
        now = datetime.now(UTC).isoformat()
        conn.execute("INSERT OR REPLACE INTO kalshi_learning_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, now, len(rows), feature_count, cross_count, 0, resolved, None, "COLLECTING_EVIDENCE" if not resolved else "RESEARCH_ONLY"))
        conn.commit()
    evidence_state = "COLLECTING" if not resolved else "RESEARCH_ONLY"
    status = {"recorded_at": now, "observations": len(rows), "derived_features": feature_count,
              "cross_market_samples": cross_count, "lead_lag_samples": 0, "resolved_markets": resolved,
              "calibration": "COLLECTING EVIDENCE" if not resolved else "RESEARCH ONLY",
              "evidence_state": evidence_state}
    out = Path(os.getenv("KALSHI_LEARNING_STATUS", "var/global-intelligence/learning-status.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    return status

if __name__ == "__main__":
    while True:
        print(json.dumps(run_once(), sort_keys=True), flush=True)
        if "--once" in os.sys.argv:
            break
        time.sleep(int(os.getenv("KALSHI_LEARNING_INTERVAL", "60")))
