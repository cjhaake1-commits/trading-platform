#!/usr/bin/env python3
"""Describe completed shadow outcomes without tuning or changing execution gates."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

DIMENSIONS = {
    "strategy": "strategy_id",
    "strategy_version": "strategy_version",
    "direction": "direction",
    "market": "market",
    "regime": "regime",
    "timeframe": "timeframe",
    "entry_threshold": "qualification_score",
    "exit_reason": "exit_reason",
    "confidence_bucket": "confidence",
    "confluence_bucket": "confluence_bucket",
}


def _bucket_threshold(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if score < 50:
        return "<50"
    if score < 70:
        return "50-69.99"
    if score < 85:
        return "70-84.99"
    return ">=85"


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    pnl = [float(row["hypothetical_pnl"] or 0.0) for row in rows]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    return {"completed": len(rows), "wins": wins, "losses": losses, "flat": len(rows) - wins - losses, "hypothetical_pnl": sum(pnl) if pnl else "UNKNOWN", "hypothetical_expectancy": sum(pnl) / len(pnl) if pnl else "UNKNOWN"}


def _group(rows: list[dict[str, object]], dimension: str) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    field = DIMENSIONS[dimension]
    for row in rows:
        if dimension == "strategy" and row.get("contributing_strategies_json"):
            try:
                keys = json.loads(str(row["contributing_strategies_json"])) or [row.get("strategy_id")]
            except json.JSONDecodeError:
                keys = [row.get("strategy_id")]
            for key in keys:
                groups[str(key or "UNKNOWN")].append(row)
            continue
        if dimension == "entry_threshold":
            key = _bucket_threshold(row.get("qualification_score"))
        elif dimension == "confidence_bucket":
            key = _bucket_confidence(row.get("confidence"))
        elif field is None:
            key = "UNKNOWN"
        else:
            key = str(row.get(field) or "UNKNOWN")
        groups[key].append(row)
    return {key: _summary(value) for key, value in sorted(groups.items())}


def _bucket_confidence(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if score < 0.5:
        return "<0.50"
    if score < 0.7:
        return "0.50-0.69"
    if score < 0.85:
        return "0.70-0.84"
    return ">=0.85"


def build_report(db_path: str = "var/autotrader/paper_experiment.db", now: datetime | None = None) -> dict[str, object]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in connection.execute(
                "SELECT pillar, strategy_id, contributing_strategies_json, strategy_version, market, direction, qualification_score, regime, timeframe, confidence, confluence_bucket, exit_reason, hypothetical_pnl "
                "FROM shadow_trades WHERE result IN ('WIN','LOSS','FLAT')"
            ).fetchall()]
        except sqlite3.OperationalError:
            rows = [dict(row) for row in connection.execute(
                "SELECT pillar, strategy_id, market, direction, qualification_score, regime, exit_reason, hypothetical_pnl "
                "FROM shadow_trades WHERE result IN ('WIN','LOSS','FLAT')"
            ).fetchall()]
    completed = [row for row in rows if row.get("pillar") == "Crypto"]
    by_dimension = {dimension: _group(completed, dimension) for dimension in DIMENSIONS}
    top = []
    for dimension, groups in by_dimension.items():
        for key, summary in groups.items():
            if key != "UNKNOWN" and summary["completed"]:
                top.append({"dimension": dimension, "key": key, **summary})
    top.sort(key=lambda item: (item["hypothetical_pnl"] if isinstance(item["hypothetical_pnl"], (int, float)) else 0, -item["completed"]))
    classification = "INSUFFICIENT_EVIDENCE" if len(completed) < 30 else ("CONCENTRATED" if top and top[0]["completed"] / len(completed) >= 0.5 else "BROAD_SYSTEMIC")
    return {"report_id": "CRYPTO_SHADOW_ATTRIBUTION", "generated_at": current.isoformat(), "scope": "completed Crypto shadow trades only", "overall": _summary(completed), "negative_expectancy_shape": classification, "by_dimension": by_dimension, "largest_negative_groups": top[:10], "evidence_limitations": ["legacy rows may still have UNKNOWN provenance; current rows are attributed only where persisted provenance exists", "descriptive attribution does not imply a threshold or exit-rule change", "actual paper economics are excluded"]}


def write_report(db_path: str = "var/autotrader/paper_experiment.db", output_dir: str = "var/reports", now: datetime | None = None) -> tuple[Path, Path]:
    report = build_report(db_path, now)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    date = (now or datetime.now(UTC)).date().isoformat()
    json_path = directory / f"shadow-attribution-{date}.json"
    md_path = directory / f"shadow-attribution-{date}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [f"# Shadow Attribution — {date}", "", f"Scope: {report['scope']}", f"Shape: {report['negative_expectancy_shape']}", "", "## Overall", "", json.dumps(report["overall"], sort_keys=True), "", "## Dimensions", ""]
    lines.extend(f"- {dimension}: {json.dumps(groups, sort_keys=True)}" for dimension, groups in report["by_dimension"].items())
    lines += ["", "## Limitations", "", *[f"- {item}" for item in report["evidence_limitations"]], ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


if __name__ == "__main__":
    print(*write_report())
