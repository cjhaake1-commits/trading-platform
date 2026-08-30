#!/usr/bin/env python3
"""Create a dated, evidence-only daily learning report for the paper lab."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, time
from pathlib import Path

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
    current = (now or datetime.now(UTC)).astimezone(UTC)
    start = datetime.combine(current.date(), time.min, tzinfo=UTC).isoformat()
    end = datetime.combine(current.date(), time.max, tzinfo=UTC).isoformat()
    rows: list[sqlite3.Row] = []
    shadows: list[sqlite3.Row] = []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT pillar,engine,candidate_status,qualification_result,rejection_reason,strategy,market_regime "
            "FROM activity_observations WHERE occurred_at BETWEEN ? AND ?", (start, end)
        ).fetchall()
        shadows = connection.execute(
            "SELECT direction,hypothetical_pnl,result,exit_reason,mfe,mae FROM shadow_trades "
            "WHERE entry_at BETWEEN ? AND ?", (start, end)
        ).fetchall()
    activity: dict[str, object] = {}
    for engine in ENGINES:
        selected = [row for row in rows if row["pillar"] in ALIASES[engine]]
        rejections = Counter(row["rejection_reason"] for row in selected if row["rejection_reason"])
        activity[engine] = {
            "observations": len(selected),
            "cycle_complete": sum(row["candidate_status"] == "CYCLE_COMPLETE" for row in selected),
            "candidates": sum(row["candidate_status"] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected),
            "signals": sum(row["candidate_status"] == "SIGNAL" for row in selected),
            "qualified": sum(row["candidate_status"] == "QUALIFIED" for row in selected),
            "top_bottlenecks": [{"reason": reason, "count": count} for reason, count in rejections.most_common(3)],
            "regimes": dict(Counter(row["market_regime"] for row in selected if row["market_regime"])),
        }
    completed = [row for row in shadows if row["result"] in {"WIN", "LOSS", "FLAT"}]
    actual = _json("var/autotrader/learning/performance_stats.json")
    provider = {name: _json(path) for name, path in {
        "Kalshi Predictions": "var/kalshi/execution-predictions.json",
        "Kalshi Perps": "var/kalshi/execution-perps.json",
    }.items()}
    return {
        "report_id": "DAILY_LEARNING",
        "date": current.date().isoformat(),
        "generated_at": current.isoformat(),
        "safety": {"live_trading_enabled": False, "mode": "paper", "real_money_orders": 0},
        "activity": activity,
        "actual_results": actual,
        "shadow_results": {
            "entries": len(shadows), "completed_experiments": len(completed),
            "wins": sum(row["result"] == "WIN" for row in completed),
            "losses": sum(row["result"] == "LOSS" for row in completed),
            "pnl": sum(float(row["hypothetical_pnl"] or 0) for row in completed),
            "exit_reasons": dict(Counter(row["exit_reason"] for row in completed)),
        },
        "provider_performance": provider,
        "evidence_limitations": [
            "estimated_edge and expected_value remain UNKNOWN until calibrated",
            "actual and shadow populations are reported separately",
            "missing provider data is retained as UNKNOWN rather than zero",
        ],
    }


def write_report(now: datetime | None = None) -> tuple[Path, Path]:
    report = build_report(now)
    date = str(report["date"])
    output_dir = Path("var/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"daily-learning-{date}.json"
    md_path = output_dir / f"daily-learning-{date}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    lines = [f"# Daily Learning — {date}", "", f"Generated: {report['generated_at']}", "", "## Safety", "", "- LIVE_TRADING_ENABLED: false", "- Real-money orders: 0", "", "## Engine activity", ""]
    for engine, values in report["activity"].items():
        lines.append(f"- {engine}: {values['observations']} observations, {values['signals']} signals, {values['qualified']} qualified")
    shadow = report["shadow_results"]
    lines += ["", "## Shadow results", "", f"- Entries: {shadow['entries']}", f"- Completed: {shadow['completed_experiments']}", f"- P&L: {shadow['pnl']}", "", "## Evidence limitations", ""]
    lines.extend(f"- {item}" for item in report["evidence_limitations"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


if __name__ == "__main__":
    print(json.dumps([str(path) for path in write_report()]))
