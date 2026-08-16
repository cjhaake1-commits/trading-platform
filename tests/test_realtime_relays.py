from datetime import UTC, datetime, timedelta

from autotrader.realtime_relays import RelayRegistry


def test_market_relay_becomes_fresh_after_observation():
    registry = RelayRegistry()
    now = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)
    registry.observe(
        "alpaca_market_stream",
        received_at=now,
        source_at=now - timedelta(milliseconds=8),
        latency_ms=8.0,
    )
    status = registry.status("alpaca_market_stream", now=now)
    assert status["fresh"] is True
    assert status["message_count"] == 1


def test_stale_relay_is_not_healthy_enabled():
    registry = RelayRegistry()
    now = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)
    registry.observe(
        "oanda_pricing_stream",
        received_at=now - timedelta(seconds=30),
        source_at=now - timedelta(seconds=30),
        latency_ms=20.0,
    )
    assert "oanda_pricing_stream" not in registry.healthy_enabled(now=now)


def test_licensed_relays_default_disabled():
    registry = RelayRegistry()
    names = {item["name"]: item for item in registry.all_status()}
    assert names["licensed_breaking_news"]["enabled"] is False
    assert names["licensed_breaking_news"]["license_required"] is True
    assert names["licensed_derivatives_intelligence"]["enabled"] is False
