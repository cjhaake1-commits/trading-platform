from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import KalshiConfig


@dataclass
class KalshiTelemetry:
    requests: int = 0
    successes: int = 0
    rate_limited: int = 0
    last_endpoint: str | None = None
    last_status: int | None = None
    last_latency_ms: float | None = None
    last_retry_after: str | None = None
    last_error: str | None = None


class KalshiReadOnlyClient:
    """Small, bounded, read-only HTTP client for the Kalshi Demo API."""

    def __init__(self, config: KalshiConfig | None = None, *, timeout: float = 10.0, max_retries: int = 1):
        self.config = config or KalshiConfig.from_env()
        if self.config.environment != "demo":
            raise ValueError("Kalshi foundation only permits the Demo environment")
        self.timeout = timeout
        self.max_retries = max(0, min(max_retries, 2))
        self.telemetry = KalshiTelemetry()

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        query = ""
        if params:
            from urllib.parse import urlencode
            query = "?" + urlencode({k: v for k, v in params.items() if v is not None})
        endpoint = path + query
        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/") + query
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            self.telemetry.requests += 1
            self.telemetry.last_endpoint = endpoint
            try:
                with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    self.telemetry.successes += 1
                    self.telemetry.last_status = response.status
                    self.telemetry.last_latency_ms = (time.monotonic() - started) * 1000
                    self.telemetry.last_retry_after = response.headers.get("Retry-After")
                    return body
            except HTTPError as exc:
                self.telemetry.last_status = exc.code
                self.telemetry.last_latency_ms = (time.monotonic() - started) * 1000
                self.telemetry.last_retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.telemetry.last_error = f"HTTP {exc.code}"
                if exc.code != 429 or attempt >= self.max_retries:
                    raise
                self.telemetry.rate_limited += 1
                time.sleep(min(float(self.telemetry.last_retry_after or 1), 2.0))
            except (URLError, TimeoutError) as exc:
                self.telemetry.last_error = type(exc).__name__
                raise
        raise RuntimeError("bounded Kalshi request exhausted")

    def events(self, **params: str) -> dict[str, Any]: return self._get("events", params)
    def markets(self, **params: str) -> dict[str, Any]: return self._get("markets", params)
    def market(self, ticker: str) -> dict[str, Any]: return self._get(f"markets/{ticker}")
    def orderbook(self, ticker: str, **params: str) -> dict[str, Any]: return self._get(f"markets/{ticker}/orderbook", params)
    def series(self, ticker: str) -> dict[str, Any]: return self._get(f"series/{ticker}")
