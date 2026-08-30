#!/usr/bin/env python3
"""Create a dated, evidence-only daily learning report for the paper lab."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from autotrader.daily_report import write_report as write_authoritative_report

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
ALIASES = {
    "Stocks": {"Stocks", "Stocks/Crypto", "alpaca_equities"},
    "Crypto": {"Crypto", "alpaca_crypto"},
    "Forex": {"Forex", "oanda_fx"},
    "Metals": {"Metals", "alpaca_metals"},
    "International": {"International", "ibkr_global"},
    "Kalshi Predictions": {"Kalshi Predictions", "kalshi_predictions"},
    "Kalshi Perps": {"Kalshi Perps", "kalshi_perps"},
}


def _json(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def build_report(now: datetime | None = None, db_path: str = "var/autotrader/paper_experiment.db") -> dict[str, object]:
    json_path, _ = write_authoritative_report(now, db_path)
    return json.loads(json_path.read_text(encoding="utf-8"))


def write_report(now: datetime | None = None) -> tuple[Path, Path]:
    report = build_report(now)
    date = str(report["date"])
    output_dir = Path("var/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"daily-learning-{date}.json"
    md_path = output_dir / f"daily-learning-{date}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    # The authoritative writer already materializes the complete Markdown
    # artifact; preserve it instead of downgrading the schema here.
    return json_path, md_path


if __name__ == "__main__":
    print(json.dumps([str(path) for path in write_report()]))
