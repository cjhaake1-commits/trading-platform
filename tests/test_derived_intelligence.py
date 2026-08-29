from __future__ import annotations

from datetime import UTC, datetime

from autotrader.derived_intelligence import DerivedIntelligenceEngine
from autotrader.public_market_intelligence import PublicIntelligenceStore, PublicObservation


def test_derived_engine_builds_microstructure_narrative_and_lead_lag_features(tmp_path):
    store = PublicIntelligenceStore(tmp_path / "public.db")
    now = datetime(2026, 8, 29, tzinfo=UTC)
    rows = []
    for index in range(30):
        for symbol, base in (("BTC-USD", 100.0), ("ETH-USD", 50.0)):
            price = base + index
            rows.append(
                PublicObservation(
                    source="coinbase", event_type="market_microstructure", observed_at=now.isoformat(),
                    symbol=symbol, value=price,
                    metadata={
                        "best_bid": price - 0.1, "best_ask": price + 0.1,
                        "bids": [[price - 0.1, "4"]], "asks": [[price + 0.1, "2"]],
                    },
                )
            )
    for index in range(20):
        rows.append(
            PublicObservation(
                source="bluesky", event_type="social_post", observed_at=now.isoformat(),
                title="bitcoin breakout momentum" if index >= 10 else "market update",
            )
        )
    store.append(rows)

    result = DerivedIntelligenceEngine(store).run(now)

    assert result["research_only"] is True
    assert result["version"] == 1
    assert result["broker_control"] is False
    assert result["state"] == "ACTIVE"
    names = {row["feature_name"] for row in store.derived_features()}
    assert {
        "spread_bps",
        "order_book_imbalance",
        "mention_velocity",
        "lead_lag_correlation",
        "source_to_return_attribution",
    } <= names
    attribution = next(row for row in store.derived_features() if row["feature_name"] == "source_to_return_attribution")
    assert attribution["metadata"]["causal"] is False


def test_empty_derived_engine_is_idle(tmp_path):
    result = DerivedIntelligenceEngine(PublicIntelligenceStore(tmp_path / "empty.db")).run()
    assert result["state"] == "IDLE"
    assert result["features_written"] == 0
