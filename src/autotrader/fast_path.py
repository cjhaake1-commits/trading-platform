from __future__ import annotations

from dataclasses import dataclass

from .low_latency import HotQuoteBook, IntelligenceCache, LatencyTrace, QuoteSnapshot


@dataclass(frozen=True)
class FastPathPolicy:
    max_quote_age_ms: float = 500.0
    max_spread_bps: float = 25.0
    require_intelligence_context: bool = False


@dataclass(frozen=True)
class FastPathDecision:
    approved: bool
    reason: str
    quote: QuoteSnapshot | None = None
    intelligence_present: bool = False


class FastPathGate:
    """Constant-time readiness gate for latency-sensitive execution.

    The gate intentionally performs no network, disk, LLM, or external-tool
    calls. Slow research must be completed before an opportunity reaches this
    boundary and stored in the in-memory IntelligenceCache.
    """

    def __init__(
        self,
        quotes: HotQuoteBook,
        intelligence: IntelligenceCache,
        policy: FastPathPolicy | None = None,
    ) -> None:
        self.quotes = quotes
        self.intelligence = intelligence
        self.policy = policy or FastPathPolicy()

    def evaluate(
        self,
        provider: str,
        symbol: str,
        *,
        now_monotonic_ns: int | None = None,
        trace: LatencyTrace | None = None,
    ) -> FastPathDecision:
        if trace is not None:
            trace.mark("gate_start", monotonic_ns=now_monotonic_ns)

        quote = self.quotes.executable(
            provider,
            symbol,
            max_age_ms=self.policy.max_quote_age_ms,
            max_spread_bps=self.policy.max_spread_bps,
            now_monotonic_ns=now_monotonic_ns,
        )
        if quote is None:
            if trace is not None:
                trace.mark("gate_reject")
            return FastPathDecision(False, "quote is missing, stale, or too wide")

        intelligence = self.intelligence.get(symbol, now_monotonic_ns=now_monotonic_ns)
        if self.policy.require_intelligence_context and intelligence is None:
            if trace is not None:
                trace.mark("gate_reject")
            return FastPathDecision(False, "required intelligence context is stale or missing", quote)

        if trace is not None:
            trace.mark("gate_approved")
        return FastPathDecision(
            True,
            "fast-path inputs are executable",
            quote,
            intelligence_present=intelligence is not None,
        )
