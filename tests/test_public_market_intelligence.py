from __future__ import annotations

from datetime import UTC, datetime

from autotrader.public_market_intelligence import (
    PublicIntelligenceCollector,
    PublicIntelligenceStore,
    PublicObservation,
    SecSubmissionsSource,
)


class FakeSource:
    name = "fake"

    def collect(self, now: datetime):
        return [
            PublicObservation(
                source=self.name,
                event_type="test",
                observed_at=now.isoformat(),
                source_time=now.isoformat(),
                symbol="SPY",
                title="test observation",
                value=1.0,
                metadata={"research_only": True},
            )
        ]


class BrokenSource:
    name = "broken"

    def collect(self, now: datetime):
        raise RuntimeError("provider unavailable")


def test_collector_persists_research_and_health_without_broker_control(tmp_path):
    store = PublicIntelligenceStore(tmp_path / "public.db")
    collector = PublicIntelligenceCollector(store=store, sources=(FakeSource(), BrokenSource()))
    result = collector.collect_once(datetime(2026, 8, 29, tzinfo=UTC))

    assert result["research_only"] is True
    assert result["broker_control"] is False
    assert result["records"] == 1
    assert result["sources"]["fake"]["state"] == "CONNECTED"
    assert result["sources"]["broken"]["state"] == "DEGRADED"

    health = {row["source"]: row for row in store.source_health()}
    assert health["fake"]["records"] == 1
    assert health["fake"]["state"] == "CONNECTED"
    assert health["broken"]["state"] == "DEGRADED"


def test_sec_source_is_idle_without_configured_ciks():
    source = SecSubmissionsSource(ciks=())
    assert source.collect(datetime(2026, 8, 29, tzinfo=UTC)) == []
