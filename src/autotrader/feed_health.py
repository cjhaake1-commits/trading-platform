from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .streaming import StreamEvent


@dataclass(frozen=True)
class FeedHealthPolicy:
    max_quote_age_seconds: float = 5.0
    max_heartbeat_age_seconds: float = 12.0
    max_latency_ms: float = 1500.0


@dataclass
class FeedHealthState:
    provider: str
    last_quote_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_source_time: datetime | None = None
    last_latency_ms: float | None = None
    symbols_seen: set[str] = field(default_factory=set)
    quote_count: int = 0
    heartbeat_count: int = 0


class FeedHealthMonitor:
    """Track feed freshness so stale or degraded data can block trading."""

    def __init__(self, policy: FeedHealthPolicy | None = None):
        self.policy = policy or FeedHealthPolicy()
        self._states: dict[str, FeedHealthState] = {}

    def observe(self, event: StreamEvent) -> None:
        state = self._states.setdefault(event.provider, FeedHealthState(event.provider))
        state.last_source_time = event.source_time
        state.last_latency_ms = event.latency_ms
        if event.kind == "quote":
            state.last_quote_at = event.received_at
            state.quote_count += 1
            if event.symbol:
                state.symbols_seen.add(event.symbol)
        elif event.kind == "heartbeat":
            state.last_heartbeat_at = event.received_at
            state.heartbeat_count += 1

    def state(self, provider: str) -> FeedHealthState | None:
        return self._states.get(provider)

    def status(self, provider: str, *, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        state = self._states.get(provider)
        if state is None:
            return {
                "provider": provider,
                "healthy": False,
                "reason": "no feed events observed",
            }

        if state.last_latency_ms is not None and state.last_latency_ms > self.policy.max_latency_ms:
            return {
                "provider": provider,
                "healthy": False,
                "reason": "feed latency exceeded limit",
                "latency_ms": state.last_latency_ms,
            }

        quote_fresh = (
            state.last_quote_at is not None
            and current - state.last_quote_at <= timedelta(seconds=self.policy.max_quote_age_seconds)
        )
        heartbeat_fresh = (
            state.last_heartbeat_at is not None
            and current - state.last_heartbeat_at
            <= timedelta(seconds=self.policy.max_heartbeat_age_seconds)
        )

        healthy = quote_fresh or heartbeat_fresh
        if quote_fresh:
            reason = "fresh quote"
        elif heartbeat_fresh:
            reason = "heartbeat alive; quotes may be unavailable or market closed"
        else:
            reason = "feed stale"

        return {
            "provider": provider,
            "healthy": healthy,
            "reason": reason,
            "last_quote_at": None if state.last_quote_at is None else state.last_quote_at.isoformat(),
            "last_heartbeat_at": (
                None if state.last_heartbeat_at is None else state.last_heartbeat_at.isoformat()
            ),
            "last_latency_ms": state.last_latency_ms,
            "symbols_seen": sorted(state.symbols_seen),
            "quote_count": state.quote_count,
            "heartbeat_count": state.heartbeat_count,
        }

    def can_trade(self, provider: str, *, now: datetime | None = None) -> bool:
        status = self.status(provider, now=now)
        # A heartbeat alone proves connectivity, not an executable market price.
        return bool(status.get("healthy")) and status.get("reason") == "fresh quote"
