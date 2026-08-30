from autotrader.paper_readiness import CHECKS, build_readiness
from autotrader.research_market_history import ResearchMarketHistory


def test_market_history_deduplicates_and_sorts(tmp_path):
    store = ResearchMarketHistory(tmp_path / "public.db")
    bars = [{"symbol": "BTC", "source_time": "2026-01-01T00:01:00+00:00", "open": 2, "high": 3, "low": 1, "close": 2.5}, {"symbol": "BTC", "source_time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": .5, "close": 2}]
    assert store.append(bars, provider="fixture", source="fixture") == 2
    assert store.append(bars, provider="fixture", source="fixture") == 0
    assert [row["source_time"] for row in store.bars("BTC", "2025", "2027")] == ["2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"]


def test_readiness_is_truthful_and_non_authorizing():
    result = build_readiness(provider_status={"CRYPTO": {"connected": True, "market_data": True}}, market_open={"CRYPTO": True})
    assert result["live_trading_enabled"] is False
    assert set(result["pillars"]["CRYPTO"]["checks"]) == set(CHECKS)
    assert result["pillars"]["CRYPTO"]["status"] == "READY"
