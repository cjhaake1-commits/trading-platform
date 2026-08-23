from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autotrader.kalshi.config import KalshiConfig
from autotrader.kalshi.exchange import ExchangeStatus, execution_gate
from autotrader.kalshi.fees import FeeRule, fee_for
from autotrader.kalshi.foundation import (
    DataQuality,
    ExpectedEdge,
    Freshness,
    PriceBand,
    Provenance,
    VariableTick,
    normalize_timestamp,
    price,
)
from autotrader.kalshi.normalization import funding_features
from autotrader.kalshi.perps.models import TransfersDisabledError, transfer
from autotrader.kalshi.perps.normalization import normalize_instrument
from autotrader.kalshi.perps.pricing import validate_price_band
from autotrader.kalshi.predictions.normalization import normalize_market


def test_exact_prices_and_variable_ticks():
    assert price("0.0001") == Decimal("0.0001")
    assert price("0.001") == Decimal("0.001")
    assert VariableTick(Decimal("0.0001")).valid(Decimal("0.1234"))
    assert not VariableTick(Decimal("0.001")).valid(Decimal("0.1234"))
    with pytest.raises(ValueError):
        VariableTick(Decimal("0"))
    assert price(price("0.0001")) == Decimal("0.0001")


def test_timestamps_are_explicit_and_timezone_safe():
    seconds = normalize_timestamp(1_700_000_000, provider_family="predictions")
    millis = normalize_timestamp(1_700_000_000_000, provider_family="perps")
    iso = normalize_timestamp("2023-11-14T22:13:20Z", provider_family="predictions")
    assert seconds.raw_type == "epoch_seconds" and millis.raw_type == "epoch_milliseconds"
    assert seconds.utc == millis.utc == iso.utc
    with pytest.raises(ValueError):
        normalize_timestamp("2023-11-14T22:13:20", provider_family="predictions")


def test_predictions_and_perps_are_distinct_and_missing_stays_missing():
    market = normalize_market({"ticker": "X", "yes_bid": "0.0001", "yes_ask": "0.001", "exchange_index": "s1"})
    instrument = normalize_instrument({"symbol": "BTC", "tick_size": "0.0001", "exchange_index": "s2"})
    assert market.yes_bid == Decimal("0.0001") and market.title is None
    assert instrument.exchange_index == "s2"


def test_price_bands_are_deterministic_and_do_not_cancel_resting_orders():
    stamp = normalize_timestamp("2026-01-01T00:00:00Z", provider_family="perps")
    band = PriceBand(Decimal("0.50"), Decimal("0.45"), Decimal("0.55"), stamp)
    assert validate_price_band(band, side="bid", price=Decimal("0.44")) is False
    assert validate_price_band(band, side="ask", price=Decimal("0.56")) is False
    assert validate_price_band(band, side="bid", price=Decimal("0.46")) is True


def test_exchange_gate_is_fail_closed_and_shard_aware():
    status = ExchangeStatus(True, True, "s1", None, "open", None, datetime.now(UTC))
    assert execution_gate(exchange=status, shard_available=True, market_available=True)
    assert not execution_gate(exchange=status, shard_available=False, market_available=True)


def test_dynamic_fee_transition_and_edge_decomposition():
    rules = [FeeRule("FED", "taker", Decimal("0.01"), datetime(2025, 1, 1, tzinfo=UTC)), FeeRule("FED", "taker", Decimal("0.02"), datetime(2026, 1, 1, tzinfo=UTC))]
    assert fee_for(rules, "FED", datetime(2025, 6, 1, tzinfo=UTC)).rate == Decimal("0.01")
    assert fee_for(rules, "FED", datetime(2026, 2, 1, tzinfo=UTC)).rate == Decimal("0.02")
    edge = ExpectedEdge(Decimal(".60"), Decimal(".50"), Decimal(".01"), Decimal(".01"), Decimal(".01"), Decimal(".02"))
    assert edge.estimated_actionable_edge == Decimal(".05")


def test_safety_locks_and_transfers():
    config = KalshiConfig()
    assert config.research_only and not config.can_trade() and not config.broker_control and config.paper_capital == 0
    with pytest.raises(TransfersDisabledError):
        transfer()


def test_funding_features_do_not_fabricate_empty_history():
    assert funding_features([]).current is None
    assert funding_features([Decimal(".01"), Decimal(".02")]).change == Decimal(".01")


def test_provenance_freshness_and_durable_family_replay_storage(tmp_path):
    retrieved = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    fresh = Freshness.from_source("2026-01-01T00:00:00Z", retrieved, provider_family="predictions")
    unavailable = Freshness.from_source(None, retrieved, provider_family="perps")
    assert fresh.quality is DataQuality.FRESH and unavailable.quality is DataQuality.UNAVAILABLE
    provenance = Provenance(family="perps", endpoint="/perps", exchange_index="shard-1", instrument="BTC")
    assert provenance.broker_control is False and provenance.execution_enabled is False
    from autotrader.kalshi.storage import KalshiResearchStore
    store = KalshiResearchStore(tmp_path / "kalshi.db")
    store.put_observation({"id": "p1", "family": "predictions", "observation_type": "probability", "retrieved_at": "now", "quality": "FRESH"})
    store.put_observation({"id": "f1", "family": "perps", "observation_type": "funding", "retrieved_at": "now", "quality": "INCOMPLETE"})
    store.put_replay_snapshot({"id": "r1", "event_id": "e1", "snapshot_label": "T-1h", "captured_at": "now", "retrieved_at": "now"})
    import sqlite3
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("select count(*) from kalshi_observations").fetchone()[0] == 2
        assert conn.execute("select count(*) from kalshi_event_replay").fetchone()[0] == 1
