from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EventMapping:
    source: str
    targets: tuple[str, ...]
    hypothesis: str
    features: tuple[str, ...] = ()


@dataclass
class GlobalEventBus:
    records: list[dict[str, Any]] = field(default_factory=list)
    def publish(self, record: dict[str, Any]) -> None:
        self.records.append({**record, "provider": "kalshi", "broker_control": False, "execution_enabled": False})


@dataclass(frozen=True)
class ReplaySnapshot:
    event_id: str
    label: str
    captured_at: datetime
    markets: dict[str, Any]


@dataclass(frozen=True)
class CounterfactualDecision:
    decision_timestamp: datetime
    opportunities: tuple[str, ...]
    chosen: str | None
    rejected: tuple[str, ...]
    expected_edge: Any
    regime: str | None = None


@dataclass(frozen=True)
class ModelTournamentEntry:
    model: str
    features: tuple[str, ...]
    outcome: str = "research-only"

