from datetime import UTC, datetime

from autotrader.fast_path import FastPathGate, FastPathPolicy
from autotrader.low_latency import HotQuoteBook, IntelligenceCache, IntelligenceSnapshot
from autotrader.streaming import StreamEvent


def quote_event(*, monotonic_ns: int = 1_000_000_000) -> StreamEvent:
    return StreamEvent(
        provider="oanda",
        kind="quote",
        symbol="EUR/USD",
        source_time=datetime(2026, 8, 16, 21, 5, tzinfo=UTC),
        received_at=datetime(2026, 8, 16, 21, 5, tzinfo=UTC),
        bid=1.10000,
        ask=1.10002,
        bid_size=1_000_000.0,
        ask_size=1_000_000.0,
        received_wall_ns=1_000_000_000,
        received_monotonic_ns=monotonic_ns,
        source_time_raw="2026-08-16T21:05:00Z",
    )


def test_hot_quote_book_accepts_fresh_tight_quote():
    book = HotQuoteBook()
    book.observe(quote_event())

    quote = book.executable(
        "oanda",
        "EUR/USD",
        max_age_ms=10.0,
        max_spread_bps=5.0,
        now_monotonic_ns=1_005_000_000,
    )

    assert quote is not None
    assert quote.age_us(1_005_000_000) == 5000.0
    assert quote.spread_bps < 5.0


def test_hot_quote_book_rejects_stale_quote():
    book = HotQuoteBook()
    book.observe(quote_event())

    quote = book.executable(
        "oanda",
        "EUR/USD",
        max_age_ms=5.0,
        max_spread_bps=5.0,
        now_monotonic_ns=1_006_000_000,
    )

    assert quote is None


def test_fast_path_can_require_precomputed_intelligence():
    book = HotQuoteBook()
    book.observe(quote_event())
    cache = IntelligenceCache()
    gate = FastPathGate(
        book,
        cache,
        FastPathPolicy(
            max_quote_age_ms=10.0,
            max_spread_bps=5.0,
            require_intelligence_context=True,
        ),
    )

    rejected = gate.evaluate(
        "oanda",
        "EUR/USD",
        now_monotonic_ns=1_005_000_000,
    )
    assert not rejected.approved

    cache.put(
        IntelligenceSnapshot(
            symbol="EUR/USD",
            generated_wall_ns=1,
            expires_monotonic_ns=1_020_000_000,
            lane_scores={"fast_features": 0.2, "trading_agents": 0.1},
            regime="opening_liquidity",
        )
    )
    approved = gate.evaluate(
        "oanda",
        "EUR/USD",
        now_monotonic_ns=1_005_000_000,
    )
    assert approved.approved
    assert approved.intelligence_present
