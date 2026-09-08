"""Fail-closed cross-pillar opportunity and capital-efficiency primitives.

This module is deliberately shadow-only: it ranks evidence supplied by
existing engines and never submits, resizes, liquidates, or reallocates an
order.  It keeps provider exposure and economic capital as separate fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class Opportunity:
    pillar: str
    engine: str
    instrument: str
    side: str
    expected_return_after_costs: float | None
    expected_loss: float | None
    confidence: float | None
    sample_quality: float | None
    liquidity: float | None
    correlation: float | None
    holding_time_minutes: float | None
    capital_required: float | None
    margin_required: float | None
    drawdown_contribution: float | None
    strategy_version: str
    execution_mode: str
    eligible: bool = False
    rejection_reason: str | None = None

    def score(self) -> float | None:
        """Risk-adjusted ranking score; unknown inputs cannot rank."""
        values = (
            self.expected_return_after_costs, self.expected_loss,
            self.confidence, self.sample_quality, self.liquidity,
            self.correlation, self.capital_required,
            self.drawdown_contribution,
        )
        if any(value is None for value in values):
            return None
        if self.capital_required <= 0 or self.expected_loss < 0:
            return None
        quality = self.confidence * self.sample_quality * self.liquidity
        risk = 1.0 + self.expected_loss + self.drawdown_contribution + self.correlation
        return (self.expected_return_after_costs / self.capital_required) * quality / risk

    def as_record(self) -> dict[str, object]:
        record = asdict(self)
        record["ranking_score"] = self.score()
        return record


def rank_shadow_opportunities(opportunities: Iterable[Opportunity]) -> list[dict[str, object]]:
    """Return eligible, fully-known opportunities in deterministic rank order."""
    ranked = []
    for opportunity in opportunities:
        score = opportunity.score()
        if not opportunity.eligible or score is None:
            continue
        ranked.append((score, opportunity.as_record()))
    ranked.sort(key=lambda item: (-item[0], item[1]["pillar"], item[1]["instrument"]))
    return [record for _, record in ranked]


def shadow_allocation(static_allocations: dict[str, float], ranked: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Record hypothetical reallocations without changing authoritative policy."""
    available = sum(max(float(value), 0.0) for value in static_allocations.values())
    result = []
    for record in ranked:
        required = float(record.get("capital_required") or 0.0)
        if required <= 0 or required > available:
            continue
        pillar = str(record["pillar"])
        current = float(static_allocations.get(pillar, 0.0))
        result.append({
            "source_policy": "STATIC_PILLAR_ALLOCATION",
            "destination_pillar": pillar,
            "instrument": record["instrument"],
            "hypothetical_capital": required,
            "static_pillar_capital": current,
            "reason": "higher risk-adjusted ranked opportunity",
            "executed": False,
        })
    return result


def margin_capability(provider: str, *, supported: bool, enabled: bool, provider_limit: float | None,
                      platform_limit: float | None, current_usage: float | None) -> dict[str, object]:
    """Normalize margin capability; unknown values remain unknown."""
    return {
        "provider": provider,
        "margin_supported": bool(supported),
        "margin_enabled": bool(enabled and supported),
        "provider_max_capability": provider_limit,
        "platform_hard_limit": platform_limit,
        "current_margin_used": current_usage,
        "fail_closed": not supported or platform_limit is None,
    }
