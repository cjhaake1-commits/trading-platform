from datetime import UTC, datetime

from autotrader.alternative_data import AlternativeSignalEngine
from autotrader.providers.quiver_signals import QuiverSignalNormalizer


def test_congress_purchase_is_positive_context():
    normalizer = QuiverSignalNormalizer()
    items = normalizer.congress(
        "NVDA",
        [
            {
                "Representative": "Example Member",
                "ReportDate": "2026-08-01",
                "Transaction": "Purchase",
            }
        ],
    )
    assert len(items) == 1
    assert items[0].score > 0
    assert items[0].commercial_use_authorized is True


def test_quiver_items_feed_alternative_signal_engine():
    normalizer = QuiverSignalNormalizer()
    items = normalizer.congress(
        "NVDA",
        [{"ReportDate": "2026-08-01", "Transaction": "Purchase"}],
    )
    context = AlternativeSignalEngine().summarize(
        "NVDA",
        items,
        now=datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert context.public_official_score is not None
    assert context.public_official_score > 0
