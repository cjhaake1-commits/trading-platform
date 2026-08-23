from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExchangeStatus:
    active: bool
    trading_active: bool
    exchange_index: str | None
    maintenance_state: str | None
    schedule_state: str | None
    next_transition: datetime | None
    retrieved_at: datetime

    def available_for_research(self) -> bool:
        return self.active and self.trading_active


@dataclass(frozen=True)
class ScheduleWindow:
    family: str
    opens_at: datetime
    closes_at: datetime
    kind: str = "trading"
    exchange_index: str | None = None


def execution_gate(*, exchange: ExchangeStatus, shard_available: bool, market_available: bool) -> bool:
    """Future fail-closed gate; no caller in this mission activates execution."""
    return exchange.active and exchange.trading_active and shard_available and market_available

