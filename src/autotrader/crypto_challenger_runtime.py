"""Governed Crypto challenger runtime adapter; Active-V2 remains quarantined."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping


@dataclass(frozen=True)
class ChallengerDecision:
    cohort: str
    state: str
    reason: str
    paper_eligible: bool
    broker_submission: bool


def evaluate_challenger(*, cohort: str, evidence: Mapping[str, object], active_quarantine: bool = True, minimum_sample: int = 30) -> dict[str, object]:
    sample = int(evidence.get("sample_size") or 0)
    expectancy = evidence.get("expectancy_after_costs")
    try: expectancy = float(expectancy) if expectancy is not None else None
    except (TypeError, ValueError): expectancy = None
    if active_quarantine and cohort == "Active-V2":
        return asdict(ChallengerDecision(cohort, "QUARANTINED", "NEGATIVE_EXISTING_EVIDENCE", False, False))
    if sample < minimum_sample or expectancy is None:
        return asdict(ChallengerDecision(cohort, "UNPROVEN", "INSUFFICIENT_OUT_OF_SAMPLE_EVIDENCE", False, False))
    if expectancy <= 0:
        return asdict(ChallengerDecision(cohort, "QUARANTINED", "NEGATIVE_EXPECTANCY_AFTER_COSTS", False, False))
    return asdict(ChallengerDecision(cohort, "PAPER_ELIGIBLE", "GOVERNANCE_EVIDENCE_THRESHOLD_MET", True, False))
