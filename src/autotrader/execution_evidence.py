"""Durable, explicitly classified paper execution evidence."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping


def persist_execution_evidence(evidence: Mapping[str, object], db_path: str | Path = "var/autotrader/research.db") -> None:
    proof = str(evidence.get("proof_type", ""))
    provider_id = evidence.get("provider_order_id") or evidence.get("provider_validation_id")
    if proof == "PROVIDER_NATIVE_ORDER" and not provider_id:
        raise ValueError("provider-native order evidence requires provider-generated ID")
    if proof == "PROVIDER_NATIVE_ORDER" and str(provider_id).startswith("SIM-"):
        raise ValueError("internal simulation ID cannot be provider-native evidence")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS execution_evidence (
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, pillar TEXT NOT NULL,
            engine TEXT, provider TEXT NOT NULL, environment TEXT NOT NULL,
            proof_type TEXT NOT NULL, purpose TEXT NOT NULL, symbol TEXT,
            provider_order_id TEXT, provider_validation_id TEXT, local_order_id TEXT,
            client_order_id TEXT, provider_status TEXT, local_status TEXT,
            submitted_at TEXT, acknowledged_at TEXT, reconciled_at TEXT,
            terminal_at TEXT, cancelled INTEGER NOT NULL, filled INTEGER NOT NULL,
            residual_position INTEGER NOT NULL, strategy_eligible INTEGER NOT NULL,
            learning_eligible INTEGER NOT NULL, performance_eligible INTEGER NOT NULL,
            evidence_json TEXT NOT NULL
        )""")
        connection.execute("""INSERT INTO execution_evidence
            (pillar,engine,provider,environment,proof_type,purpose,symbol,
             provider_order_id,provider_validation_id,local_order_id,client_order_id,
             provider_status,local_status,submitted_at,acknowledged_at,reconciled_at,
             terminal_at,cancelled,filled,residual_position,strategy_eligible,
             learning_eligible,performance_eligible,evidence_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(evidence.get("pillar", "UNKNOWN")), evidence.get("engine"),
             str(evidence.get("provider", "UNKNOWN")), str(evidence.get("environment", "UNKNOWN")),
             proof, str(evidence.get("purpose", "UNKNOWN")), evidence.get("symbol"),
             evidence.get("provider_order_id"), evidence.get("provider_validation_id"),
             evidence.get("local_order_id"), evidence.get("client_order_id"),
             evidence.get("provider_status"), evidence.get("local_status"),
             evidence.get("submitted_at"), evidence.get("acknowledged_at"),
             evidence.get("reconciled_at"), evidence.get("terminal_at"),
             int(bool(evidence.get("cancelled"))), int(bool(evidence.get("filled"))),
             int(bool(evidence.get("residual_position"))), int(bool(evidence.get("strategy_eligible"))),
             int(bool(evidence.get("learning_eligible"))), int(bool(evidence.get("performance_eligible"))),
             json.dumps(dict(evidence), sort_keys=True)))
