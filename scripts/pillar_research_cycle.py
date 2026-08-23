#!/usr/bin/env python3
"""Collect bounded, read-only market observations from the existing paper/SIM scanner."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from five_pillar_dry_run import live_candidates

from autotrader.kalshi.storage import KalshiResearchStore
from autotrader.session_state import session_state


def collect() -> dict[str, object]:
    now = datetime.now(UTC)
    db = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    KalshiResearchStore(db)
    candidates, coverage, discovery = live_candidates(now)
    import sqlite3
    stored = 0
    with sqlite3.connect(db) as conn:
        for candidate in candidates:
            pillar = str(candidate.pillar)
            symbol = str(candidate.proposal.symbol)
            # The quote is retrieved now; retain the provider bar timestamp in
            # provenance while using retrieval time for cross-market alignment.
            timestamp = now.isoformat()
            value = float(candidate.proposal.entry_price)
            row_id = hashlib.sha256(f"{pillar}|{symbol}|price|{timestamp}".encode()).hexdigest()
            conn.execute("INSERT OR REPLACE INTO kalshi_pillar_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row_id, pillar, str(candidate.broker), symbol, "price", value, timestamp,
                 f"{candidate.broker}|provider:{candidate.market_data_timestamp or 'unknown'}", "PRIMARY_SIM_DATA", "FRESH", session_state(pillar).session, "unknown", 0))
            stored += 1
    return {"recorded_at": now.isoformat(), "stored": stored, "coverage": coverage, "discovery": discovery}

if __name__ == "__main__":
    print(json.dumps(collect(), sort_keys=True))
