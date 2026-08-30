#!/usr/bin/env python3
"""Materialize activity funnel, health, and bottleneck evidence for the paper lab."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from autotrader.paper_experiment import PaperExperimentLedger

PILLARS = (
    "Stocks",
    "Crypto",
    "Forex",
    "Metals",
    "International",
    "Kalshi Predictions",
    "Kalshi Perps",
)

PILLAR_ALIASES = {
    "Stocks": {"Stocks", "alpaca_equities"},
    "Crypto": {"Crypto", "alpaca_crypto"},
    "Forex": {"Forex", "oanda_fx"},
    "Metals": {"Metals", "Metals/Commodities", "alpaca_metals"},
    "International": {"International", "ibkr_global"},
    "Kalshi Predictions": {"Kalshi Predictions", "kalshi_predictions"},
    "Kalshi Perps": {"Kalshi Perps", "kalshi_perps"},
}

FUNNEL_STAGES = (
    "UNIVERSE", "DATA_VALID", "LIQUID", "SPREAD_VALID", "CANDIDATES", "SIGNALS",
    "POSITIVE_EDGE_OR_PROXY", "RISK_APPROVED", "CAPITAL_APPROVED", "QUALIFIED",
    "ACTUAL", "SHADOW", "ORDERS", "FILLS", "EXITS", "LEARNING",
)


def _ledger_summary(path: Path) -> dict[str, dict[str, object]]:
    ledger = PaperExperimentLedger(path)
    ledger.backfill_activity_observations()
    if not path.exists():
        return {pillar: {"observations": 0, "top_rejections": []} for pillar in PILLARS}
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT pillar, candidate_status, rejection_reason, estimated_edge, expected_value, order_id, fill_id FROM activity_observations"
        ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for pillar in PILLARS:
        selected = [row for row in rows if row[0] in PILLAR_ALIASES[pillar]]
        rejections = Counter(row[2] for row in selected if row[2])
        funnel = {stage: "UNKNOWN" for stage in FUNNEL_STAGES}
        if selected:
            funnel.update({
                "CANDIDATES": sum(row[1] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected),
                "SIGNALS": sum(row[1] == "SIGNAL" for row in selected),
                "POSITIVE_EDGE_OR_PROXY": sum(row[3] is not None or row[4] is not None for row in selected),
                "QUALIFIED": sum(row[1] == "QUALIFIED" for row in selected),
                "ACTUAL": sum(row[5] is not None for row in selected),
                "ORDERS": sum(row[5] is not None for row in selected),
                "FILLS": sum(row[6] is not None for row in selected),
                "LEARNING": len(selected),
            })
        result[pillar] = {
            "observations": len(selected),
            "candidate": sum(row[1] in {"CANDIDATE", "SIGNAL", "QUALIFIED", "DECISION"} for row in selected),
            "qualified": sum(row[1] == "QUALIFIED" for row in selected),
            "rejected": sum(row[1] == "REJECTED" or row[2] is not None for row in selected),
            "top_rejections": [{"reason": reason, "count": count} for reason, count in rejections.most_common(3)],
            "funnel": funnel,
        }
    return result


def _provider_funnels() -> dict[str, object]:
    result: dict[str, object] = {}
    for name, filename in (("Kalshi Predictions", "execution-predictions.json"), ("Kalshi Perps", "execution-perps.json")):
        path = Path("var/kalshi") / filename
        if path.exists():
            try:
                result[name] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result[name] = "UNKNOWN"
        else:
            result[name] = "UNKNOWN"
    return result


def _safety_snapshot() -> dict[str, object]:
    """Return explicit safety facts for the report, never inferred from activity."""
    return {
        "mode": "paper",
        "live_trading_enabled": False,
        "real_money_orders": 0,
        "execution_policy": "paper/simulation/demo only",
    }


def main() -> None:
    payload = {
        "report_id": "HIGH_ACTIVITY_PAPER_LAB_V1",
        "created_at": datetime.now(UTC).isoformat(),
        "safety": _safety_snapshot(),
        "git_sha": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "pillars": _ledger_summary(Path("var/autotrader/paper_experiment.db")),
        "provider_funnels": _provider_funnels(),
        "health_definition": [
            "scanner_running",
            "market_data_fresh",
            "candidate_or_no_trade_decision_persisted",
            "order_capability",
            "position_management",
            "learning_persistence",
        ],
        "canonical_providers": {
            "Stocks": "Alpaca Paper", "Crypto": "Alpaca Paper", "Forex": "OANDA Practice",
            "Metals": "Alpaca Paper", "International": "Saxo SIM",
            "Kalshi Predictions": "Kalshi Demo", "Kalshi Perps": "Kalshi Demo",
        },
        "bottleneck_classification": "Evidence-based classification requires a persisted rejection reason; UNKNOWN is retained when unavailable.",
    }
    output = Path("var/reports/activity-lab-v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(output), "report_id": payload["report_id"], "git_sha": payload["git_sha"]}, sort_keys=True))


if __name__ == "__main__":
    main()
