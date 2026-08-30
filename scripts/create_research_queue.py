#!/usr/bin/env python3
"""Materialize a ranked, evidence-only research queue for the paper lab."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def _read(path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_queue(daily_path: str = "var/reports/daily-learning-2026-08-30.json") -> dict[str, object]:
    daily = _read(daily_path)
    activity = daily.get("activity") or {}
    strategy = daily.get("shadow_by_strategy") or {}
    items: list[dict[str, object]] = []

    for engine, values in activity.items():
        if not isinstance(values, dict):
            continue
        bottlenecks = values.get("top_bottlenecks") or {}
        for reason, count in bottlenecks.items():
            if not reason:
                continue
            items.append({
                "question": f"Is {reason} an appropriate gate for {engine}?",
                "scope": engine,
                "stage": "FUNNEL",
                "priority": "HIGH" if isinstance(count, int) and count >= 10 else "MEDIUM",
                "observed_count": count,
                "classification": "EVIDENCE_REQUIRED",
                "recommended_measurement": "Compare accepted and near-threshold forward populations before changing any gate.",
            })

    for name, values in strategy.items():
        if not isinstance(values, dict):
            continue
        completed = values.get("completed", 0)
        items.append({
            "question": f"Does {name} add unique forward information?",
            "scope": values.get("pillar", "UNKNOWN"),
            "stage": "STRATEGY_EVIDENCE",
            "priority": "HIGH" if isinstance(completed, int) and completed >= 30 else "MEDIUM",
            "observed_count": completed,
            "classification": values.get("evidence_classification", "UNKNOWN"),
            "recommended_measurement": "Evaluate completed actual and shadow outcomes by regime and preserve UNKNOWN for uncalibrated expectancy.",
        })

    if not items:
        items.append({
            "question": "Which missing evidence most limits the next safe decision?",
            "scope": "ALL",
            "stage": "EVIDENCE_COVERAGE",
            "priority": "HIGH",
            "observed_count": "UNKNOWN",
            "classification": "INSUFFICIENT_EVIDENCE",
            "recommended_measurement": "Increase forward observation coverage without changing paper thresholds.",
        })
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda item: (rank.get(str(item.get("priority")), 9), str(item.get("scope")), str(item.get("question"))))
    return {
        "report_id": "PAPER_LAB_RESEARCH_QUEUE",
        "generated_at": datetime.now(UTC).isoformat(),
        "safety": {"mode": "paper", "live_trading_enabled": False, "real_money_orders": 0},
        "items": items,
        "policy": "Ranked hypotheses only; no item authorizes threshold, strategy, risk, or execution changes without forward evidence and review.",
    }


def write_queue(output: str = "var/reports/research-queue.json") -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_queue(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_queue())
