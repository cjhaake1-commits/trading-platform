"""Authoritative, read-only six-pillar capital reconciliation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose

PILLARS = ("Stocks", "Forex", "Crypto", "Metals/Commodities", "International", "Kalshi")


@dataclass(frozen=True)
class PillarEquity:
    pillar: str
    allocation: float
    cash: float
    cost_basis: float
    market_value: float
    pending: float
    realized: float
    unrealized: float

    @property
    def equity(self) -> float:
        return self.cash + self.market_value + self.pending

    @property
    def deployed(self) -> float:
        return self.cost_basis

    @property
    def available(self) -> float:
        return max(self.allocation - self.cost_basis - self.pending, 0.0)

    def as_dict(self) -> dict[str, float | str]:
        row = asdict(self)
        row.update(equity=self.equity, deployed=self.deployed, available=self.available)
        return row


def reconcile_pillars(rows: list[PillarEquity], *, tolerance: float = 1e-6) -> dict[str, object]:
    unknown = [row.pillar for row in rows if row.pillar not in PILLARS]
    missing = [pillar for pillar in PILLARS if pillar not in {row.pillar for row in rows}]
    if unknown or missing:
        raise ValueError(f"invalid pillar set; missing={missing}, unknown={unknown}")
    allocation = sum(row.allocation for row in rows)
    equity = sum(row.equity for row in rows)
    realized = sum(row.realized for row in rows)
    unrealized = sum(row.unrealized for row in rows)
    deployed = sum(row.deployed for row in rows)
    pending = sum(row.pending for row in rows)
    available = sum(row.available for row in rows)
    return {
        "pillars": [row.as_dict() for row in rows],
        "starting_capital": allocation,
        "equity": equity,
        "deployed": deployed,
        "pending": pending,
        "available": available,
        "realized": realized,
        "unrealized": unrealized,
        "invariant": isclose(equity, allocation + realized + unrealized, abs_tol=tolerance),
        "allocation_invariant": all(isclose(row.allocation, row.deployed + row.pending + row.available, abs_tol=tolerance) for row in rows),
    }
