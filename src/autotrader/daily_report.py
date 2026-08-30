"""Durable dated learning report materialization for the paper lab."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, time
from pathlib import Path

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
ALIASES = {"Stocks": {"Stocks", "Stocks/Crypto", "alpaca_equities"}, "Crypto": {"Crypto", "alpaca_crypto"}, "Forex": {"Forex", "oanda_fx"}, "Metals": {"Metals", "alpaca_metals"}, "International": {"International", "ibkr_global"}, "Kalshi Predictions": {"Kalshi Predictions", "kalshi_predictions"}, "Kalshi Perps": {"Kalshi Perps", "kalshi_perps"}}


def _read(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def write_report(now: datetime | None = None, db_path: str = "var/autotrader/paper_experiment.db") -> tuple[Path, Path]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    start = datetime.combine(current.date(), time.min, tzinfo=UTC).isoformat()
    end = datetime.combine(current.date(), time.max, tzinfo=UTC).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT pillar, candidate_status, rejection_reason, market_regime FROM activity_observations WHERE occurred_at BETWEEN ? AND ?", (start, end)).fetchall()
        shadows = connection.execute("SELECT result, hypothetical_pnl, exit_reason FROM shadow_trades WHERE entry_at BETWEEN ? AND ?", (start, end)).fetchall()
    activity = {}
    for engine in ENGINES:
        selected = [row for row in rows if row["pillar"] in ALIASES[engine]]
        activity[engine] = {"observations": len(selected), "cycle_complete": sum(row["candidate_status"] == "CYCLE_COMPLETE" for row in selected), "candidates": sum(row["candidate_status"] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected), "signals": sum(row["candidate_status"] == "SIGNAL" for row in selected), "qualified": sum(row["candidate_status"] == "QUALIFIED" for row in selected), "top_bottlenecks": dict(Counter(row["rejection_reason"] for row in selected if row["rejection_reason"]).most_common(3)), "regimes": dict(Counter(row["market_regime"] for row in selected if row["market_regime"]))}
    completed = [row for row in shadows if row["result"] in {"WIN", "LOSS", "FLAT"}]
    provider_performance = {name: _read(path) for name, path in {
        "Kalshi Predictions": "var/kalshi/execution-predictions.json",
        "Kalshi Perps": "var/kalshi/execution-perps.json",
    }.items()}
    report = {"report_id": "DAILY_LEARNING", "date": current.date().isoformat(), "generated_at": current.isoformat(), "safety": {"live_trading_enabled": False, "mode": "paper", "real_money_orders": 0}, "activity": activity, "actual_results": _read("var/autotrader/learning/performance_stats.json"), "shadow_results": {"entries": len(shadows), "completed_experiments": len(completed), "wins": sum(row["result"] == "WIN" for row in completed), "losses": sum(row["result"] == "LOSS" for row in completed), "pnl": sum(float(row["hypothetical_pnl"] or 0) for row in completed), "exit_reasons": dict(Counter(row["exit_reason"] for row in completed))}, "provider_performance": provider_performance, "evidence_limitations": ["estimated_edge and expected_value remain UNKNOWN until calibrated", "actual and shadow populations are reported separately", "missing provider data is retained as UNKNOWN rather than zero"]}
    directory = Path("var/reports")
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"daily-learning-{report['date']}.json"
    md_path = directory / f"daily-learning-{report['date']}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    lines = [f"# Daily Learning — {report['date']}", "", f"Generated: {report['generated_at']}", "", "## Safety", "", "- LIVE_TRADING_ENABLED: false", "- Real-money orders: 0", "", "## Engine activity", ""]
    lines.extend(f"- {name}: {value['observations']} observations, {value['signals']} signals, {value['qualified']} qualified" for name, value in activity.items())
    lines.extend(["", "## Shadow results", "", f"- Entries: {len(shadows)}", f"- Completed: {len(completed)}", f"- P&L: {report['shadow_results']['pnl']}", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
