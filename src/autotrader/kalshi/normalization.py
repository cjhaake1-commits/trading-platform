from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FundingFeatures:
    current: Decimal | None
    change: Decimal | None
    persistence: Decimal | None
    percentile: Decimal | None


def funding_features(history: list[Decimal]) -> FundingFeatures:
    if not history:
        return FundingFeatures(None, None, None, None)
    current = history[-1]
    change = current - history[-2] if len(history) > 1 else None
    persistence = sum(1 for x in history if (x >= 0) == (current >= 0)) / len(history)
    ordered = sorted(history)
    percentile = Decimal(ordered.index(current)) / Decimal(max(1, len(ordered) - 1))
    return FundingFeatures(current, change, Decimal(str(persistence)), percentile)

