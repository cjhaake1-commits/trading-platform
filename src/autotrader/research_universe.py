"""Lawful, provenance-aware research universe policies."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.request import Request, urlopen


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
        configured = os.getenv("RESEARCH_UNIVERSE_JSON", "")
        expanded = []
        if configured:
            try:
                expanded = [Security(str(x["symbol"]).upper(), str(x.get("cik") or "") or None, x.get("company_name"), x.get("exchange"), tuple(x.get("memberships", ()))) for x in json.loads(configured)]
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                expanded = []
        securities = tuple(expanded or DEFAULT_SECURITIES)
        if symbols:
            securities = tuple(item for item in securities if item.symbol in symbols)
        return cls(securities=securities, policy=os.getenv("RESEARCH_UNIVERSE_POLICY", "UNION_CORE"))

    def records(self) -> list[dict[str, object]]:
        return [{"symbol": item.symbol, "cik": item.cik, "company_name": item.company_name,
                 "exchange": item.exchange, "memberships": list(item.memberships),
                 "membership_observed_at": item.membership_observed_at or self.generated_at,
                 "official_feed": item.official_feed, "policy": self.policy,
                 "provenance": "configured_research_universe"} for item in self.securities]

    @classmethod
    def from_sec_tickers(cls, *, user_agent: str, timeout: float = 12.0) -> "ResearchUniverse":
        request = Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": user_agent, "Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
        rows = payload.values() if isinstance(payload, dict) else payload
        dedup: dict[str, Security] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("ticker") and row.get("cik_str"):
                symbol = str(row["ticker"]).upper().strip()
                if symbol.isalnum():
                    dedup.setdefault(symbol, Security(symbol, str(row["cik_str"]).zfill(10), row.get("title"), None, ("SEC_PUBLIC_ISSUERS",)))
        return cls(tuple(dedup.values()), policy="SEC_PUBLIC_ISSUERS")
