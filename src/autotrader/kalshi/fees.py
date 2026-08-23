from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class FeeRule:
    series: str
    fee_type: str
    rate: Decimal
    effective_at: datetime
    maker_taker: str | None = None
    retrieved_at: datetime | None = None


def fee_for(rules: list[FeeRule], series: str, at: datetime) -> FeeRule | None:
    eligible = [r for r in rules if r.series == series and r.effective_at <= at]
    return max(eligible, key=lambda r: r.effective_at) if eligible else None

