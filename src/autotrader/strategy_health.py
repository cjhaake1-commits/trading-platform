"""Bounded, auditable strategy-health and learning influence decisions."""
from __future__ import annotations

import json
from pathlib import Path

STATES = {"INSUFFICIENT_SAMPLE", "EXPERIMENTAL", "HEALTHY", "WATCH", "DEGRADED", "QUARANTINED"}


def load_persisted_health(path: str = "var/reports/strategy-health.json") -> dict[tuple[str, str], dict[str, object]]:
    """Load optional governance evidence; absent evidence fails open to exploration."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("strategies", payload) if isinstance(payload, dict) else {}
    if isinstance(rows, list):
        return {(str(row.get("strategy")), str(row.get("strategy_version", "v1"))): row for row in rows if isinstance(row, dict)}
    return {(str(key[0]), str(key[1])): value for key, value in rows.items() if isinstance(key, (tuple, list)) and len(key) == 2 and isinstance(value, dict)}


def load_crypto_runtime_health(
    path: str = "var/autotrader/learning/crypto-loss-attribution.json",
    *, minimum_sample: int = 30,
) -> dict[tuple[str, str], dict[str, object]]:
    """Adapt durable Crypto outcome evidence to the existing health gate.

    This is deliberately Crypto-only: shared provider account metrics and
    health for the other pillars are not consulted or changed.  Strategy
    cohorts are retained as evidence, while the aggregate Active-V2 cohort is
    used as the conservative hierarchical fallback when specific cohorts are
    below the evidence threshold.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[tuple[str, str], dict[str, object]] = {}
    total = int(payload.get("sample_size", 0) or 0)
    aggregate = assess_strategy_health("crypto.active-v2", "v1", total, payload.get("expectancy"), minimum_sample=minimum_sample)
    aggregate["cohort_id"] = "crypto:active-v2"
    result[("crypto.active-v2", "v1")] = aggregate
    for strategy, row in (payload.get("pnl_by_strategy") or {}).items():
        if not isinstance(row, dict):
            continue
        state = assess_strategy_health(strategy, "v1", int(row.get("sample", 0) or 0), row.get("expectancy"), minimum_sample=minimum_sample)
        state["cohort_id"] = f"crypto:strategy:{strategy}"
        result[(strategy, "v1")] = state
    return result


def rank_crypto_opportunities(candidates: list[dict[str, object]], health: dict[tuple[str, str], dict[str, object]]) -> list[dict[str, object]]:
    """Apply exact strategy evidence, then the durable Active-V2 fallback."""
    ranked = rank_opportunities(candidates, health)
    broad = health.get(("crypto.active-v2", "v1"))
    if not broad or broad.get("state") != "QUARANTINED":
        return ranked
    for item in ranked:
        exact = item.get("strategy_health", {})
        if exact.get("state") in {"QUARANTINED", "HEALTHY", "WATCH"}:
            continue
        item["strategy_health"] = broad
        item["learning_adjustment"] = -1.0
        item["final_score"] = item["raw_score"] - 1.0
        item["execution_eligible"] = False
        item["shadow_eligible"] = True
        item["governance_fallback"] = "crypto:active-v2"
    return sorted(ranked, key=lambda value: value["final_score"], reverse=True)


def assess_strategy_health(strategy: str, version: str, sample_size: int, expectancy: float | None,
                           *, minimum_sample: int = 30, quarantine_expectancy: float = -0.5) -> dict[str, object]:
    if sample_size < minimum_sample:
        state = "INSUFFICIENT_SAMPLE"
    elif expectancy is None:
        state = "EXPERIMENTAL"
    elif expectancy < quarantine_expectancy:
        state = "QUARANTINED"
    elif expectancy < 0:
        state = "WATCH"
    else:
        state = "HEALTHY"
    return {"strategy": strategy, "strategy_version": version, "sample_size": sample_size,
            "expectancy": expectancy, "state": state,
            "reason": "minimum evidence threshold" if state == "INSUFFICIENT_SAMPLE" else "bounded outcome evidence"}


def rank_opportunities(candidates: list[dict[str, object]], health: dict[tuple[str, str], dict[str, object]]) -> list[dict[str, object]]:
    adjustments = {"HEALTHY": 0.10, "EXPERIMENTAL": 0.0, "INSUFFICIENT_SAMPLE": 0.0,
                   "WATCH": -0.10, "DEGRADED": -0.25, "QUARANTINED": -1.0}
    ranked = []
    for candidate in candidates:
        item = dict(candidate)
        key = (str(item.get("strategy", "")), str(item.get("strategy_version", "v1")))
        state = health.get(key, {"state": "INSUFFICIENT_SAMPLE"})
        adjustment = adjustments[str(state.get("state"))]
        item["raw_score"] = float(item.get("raw_score", item.get("score", 0.0)))
        item["learning_adjustment"] = adjustment
        item["final_score"] = item["raw_score"] + adjustment
        item["execution_eligible"] = bool(item.get("risk_approved", True)) and state.get("state") != "QUARANTINED"
        item["shadow_eligible"] = state.get("state") == "QUARANTINED"
        item["strategy_health"] = state
        ranked.append(item)
    return sorted(ranked, key=lambda value: value["final_score"], reverse=True)


def write_learning_decision_influence(path: str = "var/reports/learning-decision-influence.json") -> dict[str, object]:
    healthy = assess_strategy_health("evidence", "v2", 120, 0.8)
    quarantined = assess_strategy_health("legacy", "v1", 120, -3.0)
    ranked = rank_opportunities([
        {"candidate_id": "A", "strategy": "evidence", "strategy_version": "v2", "raw_score": 0.70, "risk_approved": True},
        {"candidate_id": "B", "strategy": "legacy", "strategy_version": "v1", "raw_score": 0.75, "risk_approved": True},
    ], {("evidence", "v2"): healthy, ("legacy", "v1"): quarantined})
    payload = {"generated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
               "candidates": ranked, "risk_controls_authoritative": True,
               "evidence": "historical attribution adjusts ranking; quarantine permits shadow only"}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
