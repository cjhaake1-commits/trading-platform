"""Adapter from intelligence records into the existing durable Learning Tree store."""
from __future__ import annotations

from typing import Mapping

from .research_platform import ResearchStore


class IntelligencePersistence:
    def __init__(self, store: ResearchStore): self.store = store

    def observation(self, record: Mapping[str, object]) -> None:
        payload = dict(record)
        payload.setdefault("promotion_status", "OBSERVING")
        payload.setdefault("paper_shadow_status", "RESEARCH_ONLY")
        payload["broker_control"] = 0
        self.store.put_research(payload)

    def feature(self, *, symbol: str, name: str, value: float, experiment_id: str, source: str = "INTELLIGENCE") -> None:
        self.store.put_feature(name=name, value=value, source=source, experiment_id=experiment_id, symbol=symbol, pillar="research")
