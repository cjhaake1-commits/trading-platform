from __future__ import annotations

import time
from dataclasses import dataclass, field

from .streaming import StreamEvent


@dataclass(frozen=True)
class QuoteSnapshot:
    provider: str
    symbol: str
    bid: float
    ask: float
    bid_size: float | None
    ask_size: float | None
    received_wall_ns: int
    received_monotonic_ns: int
    source_time_raw: str | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        if mid <= 0:
            return float("inf")
        return ((self.ask - self.bid) / mid) * 10_000.0

    def age_us(self, now_monotonic_ns: int | None = None) -> float:
        now_ns = now_monotonic_ns or time.perf_counter_ns()
        return max(now_ns - self.received_monotonic_ns, 0) / 1_000.0


class HotQuoteBook:
    """O(1) in-memory quote lookup for the execution fast path.

    Producers replace immutable snapshots. Consumers never perform network or
    disk I/O to obtain the latest quote. Persistence belongs on an asynchronous
    path so it cannot stall signal/risk/order processing.
    """

    def __init__(self) -> None:
        self._quotes: dict[tuple[str, str], QuoteSnapshot] = {}

    def observe(self, event: StreamEvent) -> QuoteSnapshot | None:
        if event.kind != "quote" or event.symbol is None:
            return None
        if event.bid is None or event.ask is None:
            return None
        if event.bid <= 0 or event.ask <= 0 or event.ask < event.bid:
            return None

        snapshot = QuoteSnapshot(
            provider=event.provider,
            symbol=event.symbol,
            bid=event.bid,
            ask=event.ask,
            bid_size=event.bid_size,
            ask_size=event.ask_size,
            received_wall_ns=event.received_wall_ns,
            received_monotonic_ns=event.received_monotonic_ns,
            source_time_raw=event.source_time_raw,
        )
        self._quotes[(event.provider, event.symbol)] = snapshot
        return snapshot

    def latest(self, provider: str, symbol: str) -> QuoteSnapshot | None:
        return self._quotes.get((provider, symbol))

    def executable(
        self,
        provider: str,
        symbol: str,
        *,
        max_age_ms: float,
        max_spread_bps: float,
        now_monotonic_ns: int | None = None,
    ) -> QuoteSnapshot | None:
        quote = self.latest(provider, symbol)
        if quote is None:
            return None
        if quote.age_us(now_monotonic_ns) > max_age_ms * 1_000.0:
            return None
        if quote.spread_bps > max_spread_bps:
            return None
        return quote


@dataclass(frozen=True)
class IntelligenceSnapshot:
    symbol: str
    generated_wall_ns: int
    expires_monotonic_ns: int
    lane_scores: dict[str, float]
    regime: str | None = None
    event_flags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def fresh(self, now_monotonic_ns: int | None = None) -> bool:
        now_ns = now_monotonic_ns or time.perf_counter_ns()
        return now_ns <= self.expires_monotonic_ns


class IntelligenceCache:
    """Precomputed research context consumed without blocking the fast path."""

    def __init__(self) -> None:
        self._items: dict[str, IntelligenceSnapshot] = {}

    def put(self, snapshot: IntelligenceSnapshot) -> None:
        self._items[snapshot.symbol] = snapshot

    def get(
        self,
        symbol: str,
        *,
        now_monotonic_ns: int | None = None,
    ) -> IntelligenceSnapshot | None:
        snapshot = self._items.get(symbol)
        if snapshot is None or not snapshot.fresh(now_monotonic_ns):
            return None
        return snapshot


@dataclass
class LatencyTrace:
    """Nanosecond-resolution internal timing for one decision/order lifecycle."""

    trace_id: str
    marks_ns: dict[str, int] = field(default_factory=dict)

    def mark(self, stage: str, *, monotonic_ns: int | None = None) -> int:
        timestamp = monotonic_ns or time.perf_counter_ns()
        self.marks_ns[stage] = timestamp
        return timestamp

    def delta_us(self, start: str, end: str) -> float | None:
        start_ns = self.marks_ns.get(start)
        end_ns = self.marks_ns.get(end)
        if start_ns is None or end_ns is None:
            return None
        return max(end_ns - start_ns, 0) / 1_000.0

    def ordered_deltas_us(self) -> dict[str, float]:
        ordered = sorted(self.marks_ns.items(), key=lambda item: item[1])
        deltas: dict[str, float] = {}
        for previous, current in zip(ordered, ordered[1:], strict=False):
            previous_name, previous_ns = previous
            current_name, current_ns = current
            deltas[f"{previous_name}->{current_name}"] = (
                max(current_ns - previous_ns, 0) / 1_000.0
            )
        return deltas
