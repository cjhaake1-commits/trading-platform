"""Durable, idempotent consumer for qualified runtime queue records."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping

from .execution_bridge import execute_qualified_queue_record, PaperAdapter
from .forward_lifecycle import ForwardLifecycle
from .forward_economic_lifecycle import EconomicLifecycle

REJECTIONS = {"INSUFFICIENT_CANONICAL_ECONOMICS", "STALE_EVIDENCE", "STRATEGY_NOT_QUALIFIED", "PROTECTED_OWNERSHIP", "PROVIDER_UNSUPPORTED", "SESSION_CLOSED", "INSUFFICIENT_CAPITAL", "RISK_REJECTED", "INSTRUMENT_CONSTRAINT", "QUARANTINED", "DUPLICATE_INTENT", "DUPLICATE_POSITION", "INVALID_CANDIDATE"}


class RuntimeExecutionConsumer:
    def __init__(self, path: str | Path = "var/autotrader/execution-intents.db", lifecycle: ForwardLifecycle | None = None, economic: EconomicLifecycle | None = None) -> None:
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lifecycle = lifecycle or ForwardLifecycle()
        self.economic = economic or EconomicLifecycle()
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_intents (
                intent_id TEXT PRIMARY KEY, state TEXT NOT NULL, reason TEXT,
                record_json TEXT NOT NULL)""")

    def consume(self, record: Mapping[str, object], *, adapter: PaperAdapter | None = None, now: str = "") -> dict[str, object]:
        intent_id = str(record.get("intent_id") or record.get("trade_id") or record.get("decision_id") or "")
        if not intent_id:
            return {"state": "REJECTED", "reason": "INVALID_CANDIDATE", "side_effects": "NONE"}
        with sqlite3.connect(self.path) as db:
            existing = db.execute("SELECT state, reason FROM execution_intents WHERE intent_id=?", (intent_id,)).fetchone()
        if existing:
            return {"state": existing[0], "reason": existing[1] or "DUPLICATE_INTENT", "side_effects": "NONE"}
        if adapter is None:
            return self._persist(intent_id, "REJECTED", "PROVIDER_UNSUPPORTED", record)
        result = execute_qualified_queue_record(record, adapter=adapter, lifecycle=self.lifecycle, now=now)
        state = "SUBMITTED" if result.get("submitted") else "REJECTED"
        if state == "SUBMITTED":
            self.economic.event(intent_id, "ORDER_INTENT", {"ownership": "PLATFORM_OWNED", "provider_order_id": result.get("provider_order_id")})
        return self._persist(intent_id, state, None if state == "SUBMITTED" else str(result.get("reason")), record, result)

    def _persist(self, intent_id: str, state: str, reason: str | None, record: Mapping[str, object], result: Mapping[str, object] | None = None) -> dict[str, object]:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR IGNORE INTO execution_intents VALUES (?,?,?,?)", (intent_id, state, reason, json.dumps({**dict(record), "result": dict(result or {})}, sort_keys=True, default=str)))
        return {"state": state, "reason": reason, "side_effects": "NONE" if state == "REJECTED" else "PAPER_PROVIDER_ONLY"}
