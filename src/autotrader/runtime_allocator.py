"""Runtime cross-pillar ranking and shadow allocation report."""

from __future__ import annotations

import json
from pathlib import Path

from .opportunity_queue import Opportunity, rank_shadow_opportunities, shadow_allocation
from .strategy_health import load_persisted_health, rank_opportunities


def refresh_allocator(
    *,
    queue_path: str | Path = "var/autotrader/opportunity-queue.jsonl",
    output: str | Path = "var/autotrader/cross-pillar-allocation.json",
    allocations: dict[str, float] | None = None,
    health: dict[tuple[str, str], dict[str, object]] | None = None,
) -> dict[str, object]:
    opportunities = []
    path = Path(queue_path)
    if path.exists():
        for line in path.read_text().splitlines()[-500:]:
            try:
                row = json.loads(line)
                data = row.get("opportunity", {})
                if row.get("decision") != "QUEUE_ELIGIBLE":
                    continue
                opportunities.append(Opportunity(**{key: data.get(key) for key in Opportunity.__dataclass_fields__}))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    ranked = rank_shadow_opportunities(opportunities)
    governance = rank_opportunities(
        [
            {
                **row,
                "strategy": row.get("engine", "unknown"),
                "raw_score": row.get("ranking_score") or 0.0,
                "risk_approved": True,
            }
            for row in ranked
        ],
        health if health is not None else load_persisted_health(),
    )
    ranked = [row for row in governance if row.get("execution_eligible")]
    capital = max(sum(max(float(value), 0.0) for value in (allocations or {}).values()), 0.0)
    selected = []
    remaining = capital
    for record in ranked:
        required = float(record.get("capital_required") or 0.0)
        if required <= 0 or required > remaining:
            continue
        selected.append(
            {
                **record,
                "allocated_capital": required,
                "allocation_scope": "SINGLE_ECONOMIC_PORTFOLIO",
                "allocation_status": "APPROVED_FOR_PROVIDER_JOB",
            }
        )
        remaining -= required
    report = {
        "ranked": ranked,
        "economic_capital": capital,
        "capital_available_after_allocation": remaining,
        "allocations": selected,
        "shadow_allocations": shadow_allocation({}, ranked),
        "governance_applied": True,
        "executed": False,
        "execution_owner": "provider_specific_runtime_job",
        "side_effects": "NONE",
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report
