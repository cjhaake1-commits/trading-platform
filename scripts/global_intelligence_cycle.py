#!/usr/bin/env python3
"""Paper-only global intelligence heartbeat; it cannot submit orders."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from autotrader.capital_allocations import SIX_PILLAR_BASE_CAPITAL, SIX_PILLARS


def cycle() -> dict[str, object]:
    db_path = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    observations = 0
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            observations = int(conn.execute("SELECT COUNT(*) FROM kalshi_observations").fetchone()[0])
    payload = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "pillars": list(SIX_PILLARS),
        "base_capital": SIX_PILLAR_BASE_CAPITAL,
        "kalshi_observations": observations,
        "best_opportunity": None,
        "best_hedge": None,
        "cash_decision": "HOLD_CASH",
        "broker_control": False,
        "execution_enabled": False,
    }
    path = Path(os.getenv("GLOBAL_INTELLIGENCE_STATUS", "var/global-intelligence/status.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(cycle(), sort_keys=True))
