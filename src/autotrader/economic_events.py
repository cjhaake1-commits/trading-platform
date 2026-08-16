from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class EventSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class EconomicEvent:
    event_id: str
    name: str
    scheduled_at: datetime
    severity: EventSeverity
    currencies: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    source: str = "official"

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")


@dataclass(frozen=True)
class EventRiskPolicy:
    high_pre_seconds: int = 180
    high_post_seconds: int = 90
    medium_pre_seconds: int = 60
    medium_post_seconds: int = 30
    high_risk_scale: float = 0.50
    medium_risk_scale: float = 0.80
    block_new_entries_seconds: int = 10


@dataclass(frozen=True)
class EventRiskAssessment:
    affected: bool
    risk_scale: float
    block_new_entries: bool
    active_events: tuple[str, ...] = ()
    reason: str = "no scheduled event risk"


class EconomicEventRiskEngine:
    """Convert known macro release times into deterministic execution controls.

    The engine does not forecast the release. It prevents a strategy from
    treating a scheduled information discontinuity as ordinary market noise.
    Existing positions may still be reduced or exited by the protective layer.
    """

    def __init__(self, policy: EventRiskPolicy | None = None) -> None:
        self.policy = policy or EventRiskPolicy()

    def assess(
        self,
        events: list[EconomicEvent],
        *,
        now: datetime | None = None,
        symbol: str | None = None,
        currencies: tuple[str, ...] = (),
    ) -> EventRiskAssessment:
        current = now or datetime.now(UTC)
        active: list[EconomicEvent] = []
        for event in events:
            if not self._relevant(event, symbol=symbol, currencies=currencies):
                continue
            if self._inside_window(event, current):
                active.append(event)

        if not active:
            return EventRiskAssessment(False, 1.0, False)

        risk_scale = 1.0
        block = False
        for event in active:
            distance = abs((event.scheduled_at - current).total_seconds())
            if distance <= self.policy.block_new_entries_seconds:
                block = True
            if event.severity is EventSeverity.HIGH:
                risk_scale = min(risk_scale, self.policy.high_risk_scale)
            elif event.severity is EventSeverity.MEDIUM:
                risk_scale = min(risk_scale, self.policy.medium_risk_scale)

        names = tuple(event.name for event in active)
        return EventRiskAssessment(
            True,
            risk_scale,
            block,
            names,
            "scheduled economic event window: " + ", ".join(names),
        )

    def _inside_window(self, event: EconomicEvent, current: datetime) -> bool:
        if event.severity is EventSeverity.HIGH:
            before = self.policy.high_pre_seconds
            after = self.policy.high_post_seconds
        elif event.severity is EventSeverity.MEDIUM:
            before = self.policy.medium_pre_seconds
            after = self.policy.medium_post_seconds
        else:
            before = after = 0
        start = event.scheduled_at - timedelta(seconds=before)
        end = event.scheduled_at + timedelta(seconds=after)
        return start <= current <= end

    @staticmethod
    def _relevant(
        event: EconomicEvent,
        *,
        symbol: str | None,
        currencies: tuple[str, ...],
    ) -> bool:
        normalized_symbol = (symbol or "").upper()
        if event.symbols and normalized_symbol in {item.upper() for item in event.symbols}:
            return True
        requested_currencies = {item.upper() for item in currencies}
        event_currencies = {item.upper() for item in event.currencies}
        if requested_currencies and requested_currencies & event_currencies:
            return True
        if normalized_symbol and event_currencies:
            compact = normalized_symbol.replace("/", "").replace("-", "").replace("_", "")
            return any(currency in compact for currency in event_currencies)
        return not event.symbols and not event.currencies
