from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kalshi_research (
 id TEXT PRIMARY KEY, event_id TEXT, market_ticker TEXT, payload_json TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'kalshi',
 broker_control INTEGER NOT NULL DEFAULT 0, execution_enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kalshi_resolutions (
 id TEXT PRIMARY KEY, market_ticker TEXT NOT NULL, probability_history_json TEXT NOT NULL,
 final_probability REAL, result TEXT, brier_score REAL, category TEXT, resolved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kalshi_shadow_hedges (
 id INTEGER PRIMARY KEY AUTOINCREMENT, market_ticker TEXT NOT NULL, payload_json TEXT NOT NULL,
 recorded_at TEXT NOT NULL, effective INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kalshi_observations (
 id TEXT PRIMARY KEY, family TEXT NOT NULL, observation_type TEXT NOT NULL,
 payload_json TEXT NOT NULL, provider_generated_at TEXT, retrieved_at TEXT NOT NULL,
 endpoint TEXT, exchange_index TEXT, instrument TEXT, normalization_version TEXT NOT NULL,
 quality TEXT NOT NULL, broker_control INTEGER NOT NULL DEFAULT 0,
 execution_enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kalshi_event_replay (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL, snapshot_label TEXT NOT NULL,
 captured_at TEXT NOT NULL, payload_json TEXT NOT NULL, family TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, normalization_version TEXT NOT NULL,
 broker_control INTEGER NOT NULL DEFAULT 0, execution_enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kalshi_global_decisions (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
 broker_control INTEGER NOT NULL DEFAULT 0, execution_enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kalshi_hedge_candidates (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
 state TEXT NOT NULL, evidence_samples INTEGER NOT NULL DEFAULT 0,
 broker_control INTEGER NOT NULL DEFAULT 0, execution_enabled INTEGER NOT NULL DEFAULT 0);
"""


class KalshiResearchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)

    def put_research(self, record: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT OR REPLACE INTO kalshi_research VALUES (?,?,?,?,?,?,?,?)", (record["id"], record.get("event_id"), record.get("market_ticker"), json.dumps(record, sort_keys=True, default=str), record["retrieved_at"], "kalshi", 0, 0))

    def put_resolution(self, record: dict[str, Any]) -> None:
        result = record.get("result")
        probability = record.get("final_probability")
        brier = (float(probability) - (1.0 if result == "yes" else 0.0)) ** 2 if probability is not None and result in {"yes", "no"} else None
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT OR REPLACE INTO kalshi_resolutions VALUES (?,?,?,?,?,?,?,?)", (record["id"], record["market_ticker"], json.dumps(record.get("probability_history", [])), probability, result, brier, record.get("category"), record["resolved_at"]))

    def put_observation(self, record: dict[str, Any]) -> None:
        """Persist a Predictions or Perps observation in the shared Kalshi DB."""
        family = record.get("family")
        if family not in {"predictions", "perps"}:
            raise ValueError("Kalshi observation family must be predictions or perps")
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kalshi_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record["id"], family, record.get("observation_type", "market"),
                 json.dumps(record.get("payload", {}), sort_keys=True, default=str),
                 record.get("provider_generated_at"), record["retrieved_at"], record.get("endpoint"),
                 record.get("exchange_index"), record.get("instrument"),
                 record.get("normalization_version", "kalshi-foundation-v2"),
                 record.get("quality", "FRESH"), 0, 0),
            )

    def put_replay_snapshot(self, record: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kalshi_event_replay VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record["id"], record["event_id"], record["snapshot_label"], record["captured_at"],
                 json.dumps(record.get("payload", {}), sort_keys=True, default=str),
                 record.get("family", "predictions"), record["retrieved_at"],
                 record.get("normalization_version", "kalshi-foundation-v2"), 0, 0),
            )
