from datetime import UTC, datetime, timedelta

from autotrader.alternative_data import (
    AlternativeSignalEngine,
    AlternativeSignalItem,
    AlternativeSource,
)


def test_combines_news_and_social_with_recency():
    now = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)
    engine = AlternativeSignalEngine()
    items = [
        AlternativeSignalItem(
            symbol="NVDA",
            source=AlternativeSource.NEWS,
            observed_at=now - timedelta(hours=2),
            score=0.8,
            confidence=0.9,
        ),
        AlternativeSignalItem(
            symbol="NVDA",
            source=AlternativeSource.SOCIAL,
            observed_at=now - timedelta(hours=1),
            score=0.4,
            confidence=0.7,
        ),
    ]

    context = engine.summarize("NVDA", items, now=now)
    assert context.included_items == 2
    assert context.excluded_items == 0
    assert context.news_score is not None
    assert context.social_score is not None
    assert 0.0 < context.combined_score <= 1.0


def test_excludes_unapproved_public_official_activity():
    now = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)
    engine = AlternativeSignalEngine()
    item = AlternativeSignalItem(
        symbol="AAPL",
        source=AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY,
        observed_at=now - timedelta(days=3),
        score=0.9,
        confidence=0.8,
        commercial_use_authorized=False,
    )

    context = engine.summarize("AAPL", [item], now=now)
    assert context.included_items == 0
    assert context.excluded_items == 1
    assert context.public_official_score is None
    assert context.combined_score == 0.0
