"""Runtime bridge from existing cycle results to the canonical opportunity queue.

The bridge is deliberately fail-closed: it consumes only fields emitted by an
engine cycle, persists an auditable decision, and never submits or resizes an
order.  Missing economics are recorded as rejected rather than guessed.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .opportunity_queue import Opportunity, rank_shadow_opportunities


def _number(data: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def persist_runtime_queue_decision(
    *, job_name: str, pillar: str, provider: str, now: datetime,
    data: Mapping[str, object], path: str | Path = "var/autotrader/opportunity-queue.jsonl",
) -> dict[str, object]:
    instrument = str(data.get("candidate") or data.get("symbol") or job_name)
    eligible = bool(data.get("qualified") or data.get("risk_approved"))
    reason = data.get("rejection") or data.get("reason") or data.get("final_bottleneck")
    opportunity = Opportunity(
        pillar=pillar, engine=job_name, instrument=instrument,
        side=str(data.get("side") or "UNKNOWN"),
        expected_return_after_costs=_number(data, "expected_return_after_costs", "expected_value", "estimated_edge"),
        expected_loss=_number(data, "expected_loss", "risk", "expected_downside"),
        confidence=_number(data, "confidence", "normalized_confidence"),
        sample_quality=_number(data, "sample_quality", "data_quality"),
        liquidity=_number(data, "liquidity"), correlation=_number(data, "correlation"),
        holding_time_minutes=_number(data, "holding_time_minutes"),
        capital_required=_number(data, "capital_required", "position_notional"),
        margin_required=_number(data, "margin_required"),
        drawdown_contribution=_number(data, "drawdown_contribution", "risk"),
        strategy_version=str(data.get("strategy_version") or "runtime-v1"),
        execution_mode=str(data.get("execution_mode") or "PAPER"),
        eligible=eligible, rejection_reason=str(reason) if reason else None,
    )
    score = opportunity.score()
    if score is None:
        eligible = False
        reason = str(reason or "INSUFFICIENT_CANONICAL_ECONOMICS")
    record = {
        "recorded_at": now.isoformat(), "job": job_name, "pillar": pillar,
        "provider": provider, "decision": "QUEUE_ELIGIBLE" if eligible and score is not None else "QUEUE_REJECTED",
        "rejection_reason": None if eligible and score is not None else str(reason),
        "opportunity": opportunity.as_record(), "execution_side_effects": "NONE",
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return record
