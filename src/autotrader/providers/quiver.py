from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class QuiverConfig:
    api_key: str
    base_url: str = "https://api.quiverquant.com"
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "QuiverConfig":
        key = os.getenv("QUIVER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("QUIVER_API_KEY is not configured")
        return cls(api_key=key)


class QuiverClient:
    """Minimal REST adapter for Quiver Quantitative datasets.

    The client returns raw records so dataset-specific normalization can remain
    explicit and testable in higher layers. It intentionally does not cache or
    redistribute responses; plan rights and rate limits remain the operator's
    responsibility.
    """

    def __init__(self, config: QuiverConfig | None = None):
        self.config = config or QuiverConfig.from_env()

    def _get(self, path: str, params: dict[str, object] | None = None) -> list[dict[str, Any]]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"

        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Accept": "application/json",
                "User-Agent": "autonomous-trading-platform/0.1",
            },
        )
        with urlopen(request, timeout=self.config.timeout_seconds) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "results", "records"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            return [payload]
        raise RuntimeError("Unexpected Quiver API response shape")

    def congress_trades(self, ticker: str) -> list[dict[str, Any]]:
        return self._get(f"beta/historical/congresstrading/{ticker.upper()}")

    def government_contracts(self, ticker: str) -> list[dict[str, Any]]:
        return self._get(f"beta/historical/govcontractsall/{ticker.upper()}")

    def lobbying(self, ticker: str) -> list[dict[str, Any]]:
        return self._get(f"beta/historical/lobbying/{ticker.upper()}")

    def corporate_donors(self, ticker: str, cycle: int | None = None) -> list[dict[str, Any]]:
        return self._get(
            "beta/bulk/corporatedonors",
            {"ticker": ticker.upper(), "cycle": cycle},
        )

    def institutional_holdings(
        self,
        ticker: str,
        *,
        most_recent: bool = True,
    ) -> list[dict[str, Any]]:
        return self._get(
            "beta/live/sec13fchanges",
            {"ticker": ticker.upper(), "most_recent": str(most_recent).lower()},
        )

    def top_shareholders(self, ticker: str) -> list[dict[str, Any]]:
        return self._get(f"beta/live/topshareholders/{ticker.upper()}")

    def off_exchange(self, ticker: str) -> list[dict[str, Any]]:
        return self._get(f"beta/historical/offexchange/{ticker.upper()}")

    def app_ratings(self) -> list[dict[str, Any]]:
        return self._get("beta/live/appratings")

    def get_full_picture(self, ticker: str, cycle: int | None = None) -> dict[str, list[dict[str, Any]]]:
        """Collect a broad, failure-tolerant dataset bundle for one ticker.

        Dataset access depends on the account tier. Unauthorized datasets are
        reported as an empty list rather than preventing access to datasets the
        account can use.
        """

        calls = {
            "congress_trades": lambda: self.congress_trades(ticker),
            "government_contracts": lambda: self.government_contracts(ticker),
            "lobbying": lambda: self.lobbying(ticker),
            "corporate_donors": lambda: self.corporate_donors(ticker, cycle),
            "institutional_holdings": lambda: self.institutional_holdings(ticker),
            "top_shareholders": lambda: self.top_shareholders(ticker),
            "off_exchange": lambda: self.off_exchange(ticker),
        }
        output: dict[str, list[dict[str, Any]]] = {}
        for name, call in calls.items():
            try:
                output[name] = call()
            except Exception:  # provider availability varies by plan and endpoint
                output[name] = []
        return output
