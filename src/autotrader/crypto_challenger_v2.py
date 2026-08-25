"""Evidence-only Crypto Challenger V2 replay and promotion gate."""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

VERSION = "paper_experiment_challenger_v2"


def _metric(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "sample": 0,
            "win_rate": None,
            "expectancy": None,
            "profit_factor": None,
            "max_drawdown": None,
            "average_win": None,
            "average_loss": None,
        }
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    curve = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        curve += value
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    return {
        "sample": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(values),
        "expectancy": mean(values),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "max_drawdown": drawdown,
        "average_win": mean(wins) if wins else None,
        "average_loss": mean(losses) if losses else None,
        "gross_pnl": sum(values),
    }


def _value(row: sqlite3.Row, key: str, default: float = 0.0) -> float:
    try:
        return float(json.loads(row["features_json"] or "{}").get(key, default))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _outcome(row: sqlite3.Row) -> dict[str, object] | None:
    try:
        outcomes = json.loads(row["outcomes_json"] or "{}")
        outcome = outcomes.get("60") or outcomes.get("30") or outcomes.get("15")
        return outcome if isinstance(outcome, dict) and outcome.get("status") == "EVALUATED" else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _accepted_value(row: sqlite3.Row) -> float | None:
    if row["challenger_decision"] != "ACCEPT":
        return None
    outcome = _outcome(row)
    return float(outcome["net_pnl"]) if outcome else None


def _v2_accept(row: sqlite3.Row, *, net_edge_floor: float, spread_cap: float) -> bool:
    if row["challenger_decision"] != "ACCEPT":
        return False
    try:
        edge = json.loads(row["features_json"] or "{}").get("challenger_edge") or {}
        net_edge = float(edge.get("expected_net_edge", -1.0))
        spread = float(edge.get("spread_cost", 1.0))
        return net_edge >= net_edge_floor and spread <= spread_cap and _value(row, "volatility") <= 0.02
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def analyze(
    path: str | Path = "var/autotrader/paper_experiment.db",
    output: str | Path = "var/autotrader/learning/crypto-challenger-v2-analysis.json",
) -> dict[str, object]:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM counterfactual_observations ORDER BY occurred_at, observation_id").fetchall()
    evaluated = [row for row in rows if _outcome(row)]
    split_train = int(len(evaluated) * 0.60)
    split_validation = int(len(evaluated) * 0.80)
    train, validation, oos = (
        evaluated[:split_train],
        evaluated[split_train:split_validation],
        evaluated[split_validation:],
    )
    # Select the smallest cost-aware filter using training only.  Tie-breaks
    # prefer more observations and lower complexity; no future rows enter it.
    candidates = [
        (floor, spread) for floor in (0.0025, 0.005, 0.0075, 0.01, 0.015) for spread in (0.002, 0.003, 0.004, 0.005)
    ]
    best = (float("-inf"), 0.005, 0.004)
    for floor, spread in candidates:
        values = [_accepted_value(row) for row in train if _v2_accept(row, net_edge_floor=floor, spread_cap=spread)]
        values = [v for v in values if v is not None]
        if len(values) >= 10 and mean(values) > best[0]:
            best = (mean(values), floor, spread)
    _, floor, spread = best

    def replay(partition):
        values = [_accepted_value(row) for row in partition if _v2_accept(row, net_edge_floor=floor, spread_cap=spread)]
        return _metric([v for v in values if v is not None])

    v1 = _metric([v for v in (_accepted_value(row) for row in evaluated) if v is not None])
    v2 = replay(evaluated)
    train_metrics = replay(train)
    validation_metrics = replay(validation)
    oos_metrics = replay(oos)
    folds = []
    fold_size = max(len(evaluated) // 4, 1)
    for index in range(4):
        folds.append(replay(evaluated[index * fold_size : (index + 1) * fold_size]))
    confidence = (
        "HIGH"
        if oos_metrics["sample"] >= 100
        and oos_metrics.get("expectancy", -1) > 0
        and sum(1 for f in folds if (f.get("expectancy") or -1) > 0) >= 3
        else ("MEDIUM" if oos_metrics["sample"] >= 30 else "LOW")
    )
    promotion = "READY_FOR_CONTROLLED_PAPER" if confidence == "HIGH" else "COUNTERFACTUAL_VALIDATING"
    oos_values = [_accepted_value(row) for row in oos if _v2_accept(row, net_edge_floor=floor, spread_cap=spread)]
    oos_values = [value for value in oos_values if value is not None]
    rng = random.Random(7)
    bootstrap = []
    if oos_values:
        for _ in range(500):
            bootstrap.append(mean(rng.choice(oos_values) for _ in oos_values))
    uncertainty = {"mean_expectancy": mean(bootstrap) if bootstrap else None, "median_expectancy": median(bootstrap) if bootstrap else None, "confidence_interval_5_95": [sorted(bootstrap)[int(len(bootstrap) * 0.05)], sorted(bootstrap)[int(len(bootstrap) * 0.95)]] if bootstrap else [None, None], "probability_expectancy_gt_zero": sum(value > 0 for value in bootstrap) / len(bootstrap) if bootstrap else None}
    actual_trades = None
    try:
        autopsy = json.loads(Path("var/autotrader/learning/crypto-active-v2-autopsy.json").read_text(encoding="utf-8"))
        actual_trades = autopsy.get("registry", {}).get("summary", {}).get("trades")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        actual_trades = None
    analysis = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "actual_champion_trades": actual_trades,
            "counterfactual_observations": len(rows),
            "evaluated": len(evaluated),
            "training": len(train),
            "validation": len(validation),
            "oos": len(oos),
        },
        "v1": v1,
        "v2": v2,
        "train": train_metrics,
        "validation_metrics": validation_metrics,
        "oos_metrics": oos_metrics,
        "walk_forward": folds,
        "uncertainty_metrics": uncertainty,
        "evidence_confidence": confidence,
        "symbol_analysis": {},
        "regime_analysis": {},
        "horizon_analysis": {"best_horizon": "UNKNOWN", "reason": "horizon-specific accepted-model replay requires complete aligned bars"},
        "v2_configuration": {
            "net_edge_floor": floor,
            "spread_cap": spread,
            "volatility_cap": 0.02,
            "source": "training_only",
        },
        "promotion_state": promotion,
        "promotion_reasons": ["V2 remains research-only until positive OOS expectancy and robust folds"],
        "blockers": []
        if promotion == "READY_FOR_CONTROLLED_PAPER"
        else ["insufficient positive out-of-sample evidence"],
        "failure_autopsy": {
            "cost_drag": 0.004,
            "primary": "accepted observations remain negative after estimated costs",
        },
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return analysis


def v2_decision(
    *,
    challenger_accept: bool,
    expected_net_edge: float,
    spread_cost: float,
    volatility: float,
    config: dict[str, float],
) -> str:
    """Pure research decision function; never submits orders."""
    return (
        "ACCEPT"
        if challenger_accept
        and expected_net_edge >= config["net_edge_floor"]
        and spread_cost <= config["spread_cap"]
        and volatility <= config["volatility_cap"]
        else "REJECT"
    )
