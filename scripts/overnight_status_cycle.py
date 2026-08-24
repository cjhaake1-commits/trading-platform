#!/usr/bin/env python3
"""Write a non-secret rolling overnight operations snapshot."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def _read(path: str) -> dict[str, object]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_report() -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    predictions = _read("var/kalshi/execution-predictions.json")
    perps = _read("var/kalshi/execution-perps.json")
    learning = _read("var/global-intelligence/learning-status.json")
    counts = {"observations": 0, "features": 0, "cross_market_samples": 0}
    try:
        with sqlite3.connect("var/kalshi/research.db") as conn:
            counts = {
                "observations": conn.execute("SELECT COUNT(*) FROM kalshi_observations").fetchone()[0],
                "features": conn.execute("SELECT COUNT(*) FROM kalshi_learning_features").fetchone()[0],
                "cross_market_samples": conn.execute("SELECT COUNT(*) FROM kalshi_cross_market_samples").fetchone()[0],
            }
    except sqlite3.Error:
        pass
    report = {"timestamp": now, "safety": {"live_trading_enabled": False, "kalshi_environment": "demo", "broker_control": False},
              "predictions": predictions, "perps": perps, "learning": {**learning, **counts}, "capital": {"authorized": 1000.0, "committed": 0.0, "available": 1000.0}}
    out = Path("var/autotrader/overnight-status.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path("var/autotrader/overnight-report.txt").write_text(
        "Overnight status " + now + "\n" + json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(json.dumps(write_report(), sort_keys=True))
