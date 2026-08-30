"""Durable dated learning report materialization for the paper lab."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

ENGINES = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
ALIASES = {"Stocks": {"Stocks", "Stocks/Crypto", "alpaca_equities"}, "Crypto": {"Crypto", "alpaca_crypto"}, "Forex": {"Forex", "oanda_fx"}, "Metals": {"Metals", "alpaca_metals"}, "International": {"International", "ibkr_global"}, "Kalshi Predictions": {"Kalshi Predictions", "kalshi_predictions"}, "Kalshi Perps": {"Kalshi Perps", "kalshi_perps"}}
CURRENT_STRATEGIES = {
    "MOMENTUM",
    "BREAKOUT",
    "MEAN_REVERSION",
    "TREND_FOLLOWING",
    "RELATIVE_STRENGTH",
    "SESSION_MOMENTUM",
    "VOLATILITY_EXPANSION",
}


def _strategy_classification(strategy: str) -> str:
    normalized = strategy.upper().replace("CRYPTO.", "")
    if normalized in CURRENT_STRATEGIES:
        return "CURRENT_MULTI_STRATEGY"
    if "POSITION_MANAGEMENT" in normalized or normalized in {"CANDIDATE_OBSERVATION", "CYCLE"}:
        return "INFRASTRUCTURE"
    return "LEGACY_BASELINE"


def _evidence_classification(completed: int, expectancy: float | None) -> str:
    if completed < 30:
        return "INSUFFICIENT_EVIDENCE"
    if expectancy is not None and expectancy > 0 and completed >= 100:
        return "PROMISING"
    return "EARLY_SIGNAL"


def _bottleneck_classification(reason: str) -> tuple[str, str]:
    normalized = reason.upper()
    if any(token in normalized for token in ("EXCEPTION", "TRACEBACK", "BUG")):
        return "BUG", "Capture the failing path, add a regression, and repair before changing gates."
    if any(token in normalized for token in ("SESSION", "LIQUID", "SPREAD", "PROVIDER_MINIMUM", "CLOSED")):
        return "LEGITIMATE", "Preserve the gate and continue measuring eligible forward observations."
    return "OPTIMIZABLE", "Compare accepted and near-threshold forward populations before changing this gate."


def _read(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def _provider_metrics() -> dict[str, object]:
    job_map = {
        "Alpaca": {"autonomous-paper-trading", "alpaca-metals-paper-trading", "crypto-market-data-archive"},
        "OANDA": {"oanda-fx-paper-trading"},
        "Saxo": {"saxo-international-paper-trading"},
    }
    result = {name: "UNKNOWN" for name in job_map}
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with sqlite3.connect("var/autotrader/audit.db", timeout=30.0) as connection:
            rows = connection.execute(
                "SELECT data_json, created_at FROM audit_events WHERE event_type='runtime_job' AND created_at >= ?",
                (cutoff,),
            ).fetchall()
        for provider, jobs in job_map.items():
            entries = []
            for raw, created_at in rows:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("job") in jobs:
                    entries.append((data, created_at))
            durations = sorted(float(data["duration_ms"]) for data, _ in entries if data.get("duration_ms") is not None)
            successes = [created_at for data, created_at in entries if data.get("ok") is True]
            retry_values = [
                int(data[key])
                for data, _ in entries
                for key in ("broker_retries", "retries")
                if isinstance(data.get(key), (int, float))
            ]
            timeout_values = [
                int(data[key])
                for data, _ in entries
                for key in ("broker_timeouts", "timeouts")
                if isinstance(data.get(key), (int, float))
            ]
            result[provider] = {
                "status": "CONNECTED" if successes else ("DEGRADED" if entries else "UNKNOWN"),
                "requests_job_proxy": len(entries) if entries else "UNKNOWN",
                "successes": len(successes) if entries else "UNKNOWN",
                "failures": sum(data.get("ok") is False for data, _ in entries) if entries else "UNKNOWN",
                "timeouts": sum(timeout_values) if timeout_values else "UNKNOWN",
                "retries": sum(retry_values) if retry_values else "UNKNOWN",
                "measurement_scope": "runtime_job_proxy",
                "last_success": max(successes, default="UNKNOWN"),
                "p50_latency_ms_job_proxy": durations[(len(durations) - 1) // 2] if durations else "UNKNOWN",
                "p95_latency_ms_job_proxy": durations[max(0, (len(durations) * 95 + 99) // 100 - 1)] if durations else "UNKNOWN",
            }
    except sqlite3.Error:
        pass
    return result


def write_report(now: datetime | None = None, db_path: str = "var/autotrader/paper_experiment.db") -> tuple[Path, Path]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    start = datetime.combine(current.date(), time.min, tzinfo=UTC).isoformat()
    end = datetime.combine(current.date(), time.max, tzinfo=UTC).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT pillar, strategy, candidate_status, rejection_reason, market_regime FROM activity_observations WHERE occurred_at BETWEEN ? AND ?", (start, end)).fetchall()
        try:
            shadows = connection.execute("SELECT pillar, strategy_id, contributing_strategies_json, result, hypothetical_pnl, exit_reason, mfe, mae, entry_at, exit_at FROM shadow_trades WHERE entry_at BETWEEN ? AND ?", (start, end)).fetchall()
        except sqlite3.OperationalError:
            shadows = connection.execute("SELECT pillar, strategy_id, NULL AS contributing_strategies_json, result, hypothetical_pnl, exit_reason, mfe, mae, entry_at, exit_at FROM shadow_trades WHERE entry_at BETWEEN ? AND ?", (start, end)).fetchall()
    activity = {}
    strategy_evidence = {}
    for row in rows:
        strategy = row["strategy"] or "UNKNOWN"
        item = strategy_evidence.setdefault(strategy, {"classification": _strategy_classification(strategy), "observations": 0, "signals": 0, "qualified": 0, "regimes": {}})
        item["observations"] += 1
        item["signals"] += row["candidate_status"] == "SIGNAL"
        item["qualified"] += row["candidate_status"] == "QUALIFIED"
        regime = row["market_regime"] or "UNKNOWN"
        item["regimes"][regime] = item["regimes"].get(regime, 0) + 1
    for engine in ENGINES:
        selected = [row for row in rows if row["pillar"] in ALIASES[engine]]
        top_bottlenecks = dict(Counter(row["rejection_reason"] for row in selected if row["rejection_reason"]).most_common(3))
        bottlenecks = []
        for reason, count in top_bottlenecks.items():
            classification, action = _bottleneck_classification(reason)
            bottlenecks.append({"stage": "FUNNEL", "reason": reason, "count": count, "impact_pct": round(count * 100 / len(selected), 2) if selected else "UNKNOWN", "classification": classification, "recommended_action": action})
        activity[engine] = {"observations": len(selected), "cycle_complete": sum(row["candidate_status"] == "CYCLE_COMPLETE" for row in selected), "candidates": sum(row["candidate_status"] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected), "signals": sum(row["candidate_status"] == "SIGNAL" for row in selected), "qualified": sum(row["candidate_status"] == "QUALIFIED" for row in selected), "top_bottlenecks": top_bottlenecks, "bottlenecks": bottlenecks, "regimes": dict(Counter(row["market_regime"] for row in selected if row["market_regime"]))}
    completed = [row for row in shadows if row["result"] in {"WIN", "LOSS", "FLAT"}]
    wins = [row for row in completed if row["result"] == "WIN"]
    losses = [row for row in completed if row["result"] == "LOSS"]
    pnl_values = [float(row["hypothetical_pnl"] or 0.0) for row in completed]
    positive_pnl = [value for value in pnl_values if value > 0]
    negative_pnl = [value for value in pnl_values if value < 0]
    holding_seconds = []
    for row in completed:
        if row["entry_at"] and row["exit_at"]:
            try:
                holding_seconds.append((datetime.fromisoformat(row["exit_at"]) - datetime.fromisoformat(row["entry_at"])).total_seconds())
            except ValueError:
                continue
    shadow_scorecard = {
        "completed_experiments": len(completed), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(completed) if completed else "UNKNOWN",
        "average_win": sum(positive_pnl) / len(positive_pnl) if positive_pnl else "UNKNOWN",
        "average_loss": sum(negative_pnl) / len(negative_pnl) if negative_pnl else "UNKNOWN",
        "hypothetical_expectancy": sum(pnl_values) / len(pnl_values) if pnl_values else "UNKNOWN",
        "profit_factor": sum(positive_pnl) / abs(sum(negative_pnl)) if negative_pnl else "UNKNOWN",
        "hypothetical_pnl": sum(pnl_values) if pnl_values else "UNKNOWN",
        "average_mfe": sum(float(row["mfe"] or 0.0) for row in completed) / len(completed) if completed else "UNKNOWN",
        "average_mae": sum(float(row["mae"] or 0.0) for row in completed) / len(completed) if completed else "UNKNOWN",
        "average_holding_seconds": sum(holding_seconds) / len(holding_seconds) if holding_seconds else "UNKNOWN",
    }
    shadow_by_pillar = {}
    for pillar in sorted({row["pillar"] for row in shadows}):
        pillar_rows = [row for row in shadows if row["pillar"] == pillar]
        pillar_completed = [row for row in pillar_rows if row["result"] in {"WIN", "LOSS", "FLAT"}]
        pillar_pnl = [float(row["hypothetical_pnl"] or 0.0) for row in pillar_completed]
        pillar_positive = sum(value for value in pillar_pnl if value > 0)
        pillar_negative = abs(sum(value for value in pillar_pnl if value < 0))
        shadow_by_pillar[pillar] = {
            "entries": len(pillar_rows),
            "completed": len(pillar_completed),
            "wins": sum(row["result"] == "WIN" for row in pillar_completed),
            "losses": sum(row["result"] == "LOSS" for row in pillar_completed),
            "hypothetical_pnl": sum(pillar_pnl) if pillar_pnl else "UNKNOWN",
            "hypothetical_expectancy": sum(pillar_pnl) / len(pillar_pnl) if pillar_pnl else "UNKNOWN",
            "profit_factor": pillar_positive / pillar_negative if pillar_negative else ("UNKNOWN" if not pillar_positive else "INF"),
        }
    shadow_by_strategy = {}
    strategy_rows_by_id = {}
    for row in shadows:
        strategy_ids = [row["strategy_id"]]
        raw_provenance = row["contributing_strategies_json"]
        if raw_provenance:
            try:
                strategy_ids = json.loads(raw_provenance) or strategy_ids
            except (TypeError, json.JSONDecodeError):
                pass
        for strategy_id in strategy_ids:
            strategy_rows_by_id.setdefault(str(strategy_id), []).append(row)
    for strategy_id in sorted(strategy_rows_by_id):
        strategy_rows = strategy_rows_by_id[strategy_id]
        strategy_completed = [row for row in strategy_rows if row["result"] in {"WIN", "LOSS", "FLAT"}]
        strategy_pnl = [float(row["hypothetical_pnl"] or 0.0) for row in strategy_completed]
        strategy_expectancy = sum(strategy_pnl) / len(strategy_pnl) if strategy_pnl else None
        strategy_positive = sum(value for value in strategy_pnl if value > 0)
        strategy_negative = abs(sum(value for value in strategy_pnl if value < 0))
        shadow_by_strategy[strategy_id] = {
            "entries": len(strategy_rows),
            "completed": len(strategy_completed),
            "wins": sum(row["result"] == "WIN" for row in strategy_completed),
            "losses": sum(row["result"] == "LOSS" for row in strategy_completed),
            "hypothetical_pnl": sum(strategy_pnl) if strategy_pnl else "UNKNOWN",
            "hypothetical_expectancy": strategy_expectancy if strategy_expectancy is not None else "UNKNOWN",
            "profit_factor": strategy_positive / strategy_negative if strategy_negative else ("UNKNOWN" if not strategy_positive else "INF"),
            "evidence_classification": _evidence_classification(len(strategy_completed), strategy_expectancy),
            "governance_status": "EXPERIMENTAL",
        }
    provider_performance = {name: _read(path) for name, path in {
        "Kalshi Predictions": "var/kalshi/execution-predictions.json",
        "Kalshi Perps": "var/kalshi/execution-perps.json",
    }.items()}
    provider_performance.update(_provider_metrics())
    report = {"report_id": "DAILY_LEARNING", "date": current.date().isoformat(), "generated_at": current.isoformat(), "safety": {"live_trading_enabled": False, "mode": "paper", "real_money_orders": 0}, "activity": activity, "strategy_evidence": strategy_evidence, "actual_results": _read("var/autotrader/learning/performance_stats.json"), "shadow_results": {"entries": len(shadows), "completed_experiments": len(completed), "wins": sum(row["result"] == "WIN" for row in completed), "losses": sum(row["result"] == "LOSS" for row in completed), "pnl": sum(float(row["hypothetical_pnl"] or 0) for row in completed), "exit_reasons": dict(Counter(row["exit_reason"] for row in completed))}, "shadow_scorecard": shadow_scorecard, "shadow_by_pillar": shadow_by_pillar, "shadow_by_strategy": shadow_by_strategy, "provider_performance": provider_performance, "evidence_limitations": ["estimated_edge and expected_value remain UNKNOWN until calibrated", "actual and shadow populations are reported separately", "missing provider data is retained as UNKNOWN rather than zero", "strategy evidence is descriptive and does not imply governance promotion"]}
    directory = Path("var/reports")
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"daily-learning-{report['date']}.json"
    md_path = directory / f"daily-learning-{report['date']}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    lines = [f"# Daily Learning — {report['date']}", "", f"Generated: {report['generated_at']}", "", "## Safety", "", "- LIVE_TRADING_ENABLED: false", "- Real-money orders: 0", "", "## Engine activity", ""]
    lines.extend(f"- {name}: {value['observations']} observations, {value['signals']} signals, {value['qualified']} qualified" for name, value in activity.items())
    lines.extend(["", "## Actual paper results", ""])
    actual = report["actual_results"]
    if isinstance(actual, dict):
        for key in ("completed_trades", "wins", "losses", "win_rate", "expectancy", "profit_factor", "cumulative_realized_pnl"):
            lines.append(f"- {key}: {actual.get(key, 'UNKNOWN')}")
    else:
        lines.append("- UNKNOWN")
    lines.extend(["", "## Shadow results", "", f"- Entries: {len(shadows)}", f"- Completed: {len(completed)}", f"- P&L: {report['shadow_results']['pnl']}"])
    for key in ("wins", "losses", "win_rate", "hypothetical_expectancy", "profit_factor", "average_mfe", "average_mae", "average_holding_seconds"):
        lines.append(f"- {key}: {shadow_scorecard.get(key, 'UNKNOWN')}")
    lines.extend(["", "## Provider performance", ""])
    for provider, metrics in provider_performance.items():
        lines.append(f"- {provider}: {json.dumps(metrics, sort_keys=True, default=str)}")
    lines.extend(["", "## Evidence limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report["evidence_limitations"])
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
