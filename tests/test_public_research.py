from datetime import UTC, datetime

from autotrader.public_research import normalize_13f, normalize_news, normalize_public_observation


def test_public_observation_has_provenance_and_idempotent_identity():
    kwargs = dict(source="fed", provider="Federal Reserve", endpoint="https://example.test",
                  pillar="forex", source_quality="official", instrument="USD", observed_at="2026-08-23T12:00:00Z",
                  retrieved_at=datetime(2026, 8, 23, tzinfo=UTC))
    first = normalize_public_observation("macro", {"value": 1}, **kwargs)
    second = normalize_public_observation("macro", {"value": 1}, **kwargs)
    assert first.observation_id == second.observation_id
    assert first.source_quality == "OFFICIAL"
    assert first.as_research_record()["broker_control"] == 0


def test_13f_and_news_are_normalized_into_research_lanes():
    filing = normalize_13f({"institution": "Fund", "ticker": "SPY", "filing_date": "2026-08-01"}, endpoint="sec://filing")
    news = normalize_news({"source": "Reuters", "symbol": "SPY", "timestamp": "2026-08-23T12:00:00Z"}, endpoint="news://item")
    assert filing.lane == "institutional" and filing.source_quality == "REGULATORY"
    assert news.lane == "news" and news.instrument == "SPY"
