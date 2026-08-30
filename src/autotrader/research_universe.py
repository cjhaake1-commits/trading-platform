"""Lawful, provenance-aware research universe policies."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class Security:
    symbol: str
    cik: str | None = None
    company_name: str | None = None
    exchange: str | None = None
    memberships: tuple[str, ...] = ()
    membership_observed_at: str | None = None
    official_feed: bool = False


DEFAULT_SECURITIES = (
    Security("AAPL", "0000320193", "Apple Inc.", "NASDAQ", ("SP500", "NASDAQ_100")),
    Security("MSFT", "0000789019", "Microsoft Corp.", "NASDAQ", ("SP500", "NASDAQ_100")),
    Security("NVDA", "0001045810", "NVIDIA Corp.", "NASDAQ", ("SP500", "NASDAQ_100")),
)


@dataclass
class ResearchUniverse:
    securities: tuple[Security, ...] = DEFAULT_SECURITIES
    policy: str = "UNION_CORE"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def configured(cls) -> "ResearchUniverse":
        symbols = {item.strip().upper() for item in os.getenv("RESEARCH_SYMBOLS", "").split(",") if item.strip()}
        securities = tuple(item for item in DEFAULT_SECURITIES if not symbols or item.symbol in symbols)
        return cls(securities=securities, policy=os.getenv("RESEARCH_UNIVERSE_POLICY", "UNION_CORE"))

    def records(self) -> list[dict[str, object]]:
        return [{"symbol": item.symbol, "cik": item.cik, "company_name": item.company_name,
                 "exchange": item.exchange, "memberships": list(item.memberships),
                 "membership_observed_at": item.membership_observed_at or self.generated_at,
                 "official_feed": item.official_feed, "policy": self.policy,
                 "provenance": "configured_research_universe"} for item in self.securities]
