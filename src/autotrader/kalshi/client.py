from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .auth import KalshiAuthReference
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
        self.auth = KalshiAuthReference.from_config(self.config)

    def _url(self, path: str, family: str = "predictions") -> str:
        base = self.config.predictions_rest_url if family == "predictions" else self.config.perps_rest_url
        if not base:
            raise RuntimeError("Kalshi Perps/Margin Demo endpoint is not documented/configured")
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(base)
        if parsed.hostname not in {"external-api.demo.kalshi.co", "demo-api.kalshi.co"}:
            raise ValueError("Kalshi client rejects non-Demo URL")
        return base.rstrip("/") + "/" + path.lstrip("/")

    def _get(self, path: str, params: dict[str, str] | None = None, *, authenticated: bool = False, family: str = "predictions") -> dict[str, Any]:
        query = ""
        if params:
            from urllib.parse import urlencode
            query = "?" + urlencode({k: v for k, v in params.items() if v is not None})
        endpoint = path + query
        url = self._url(path, family) + query
        headers = {"Accept": "application/json"}
        if authenticated:
            headers.update(self.auth.sign("GET", __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).path))
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            self.telemetry.requests += 1
            self.telemetry.last_endpoint = endpoint
            try:
                with urlopen(Request(url, method="GET", headers=headers), timeout=self.timeout) as response:
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
                if exc.code in {500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
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

    def request(self, path: str, *, params: dict[str, str] | None = None, authenticated: bool = False, family: str = "predictions") -> dict[str, Any]:
        return self._get(path, params, authenticated=authenticated, family=family)

    def exchange_status(self): return self._get("exchange/status")
    def exchange_schedule(self): return self._get("exchange/schedule")
    def user_data_timestamp(self): return self._get("exchange/user_data_timestamp", authenticated=True)
    def fee_changes(self, **params): return self._get("series/fee_changes", params)
    def positions(self, **params): return self._get("portfolio/positions", params, authenticated=True)
    def balance(self): return self._get("portfolio/balance", authenticated=True)
    def fills(self, **params): return self._get("portfolio/fills", params, authenticated=True)
    def orders_read_only(self, **params): return self._get("portfolio/orders", params, authenticated=True)

    def perps(self, path: str, **params):
        """Call a documented Perps/Margin path, never the Predictions API."""
        if not path:
            raise ValueError("Perps/Margin path is required")
        return self._get(path, params, authenticated=True, family="perps")

    def perps_enabled(self): return self.perps("enabled")
    def perps_markets(self, **params): return self.perps("markets", **params)
    def perps_market(self, ticker: str): return self.perps(f"markets/{ticker}")
    def perps_orderbook(self, ticker: str): return self.perps(f"markets/{ticker}/orderbook")
    def perps_balance(self): return self.perps("balance")
    def perps_risk(self): return self.perps("risk")
    def perps_positions(self, **params): return self.perps("positions", **params)
    def perps_fills(self, **params): return self.perps("fills", **params)
    def perps_funding_rate(self, **params): return self.perps("funding/rate", **params)
    def perps_funding_history(self, **params): return self.perps("funding/rates/historical", **params)
    def perps_fee_tiers(self): return self.perps("fees/tiers")


class KalshiDemoExecutionClient(KalshiReadOnlyClient):
    """Explicitly guarded Demo mutation transport.

    Research/scanner code continues to use ``KalshiReadOnlyClient``.  This
    separate transport refuses every non-Demo configuration and requires the
    explicit Demo execution gate before a mutation can be sent.
    """

    def _mutation(self, method: str, path: str, payload: dict[str, Any] | None = None,
                  *, family: str = "predictions") -> dict[str, Any]:
        if not self.config.demo_trading_enabled or self.config.environment != "demo":
            raise RuntimeError("Kalshi Demo execution gate is not enabled")
        url = self._url(path, family)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.auth.sign(method, __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).path))
        request = Request(url, method=method.upper(), headers=headers,
                          data=None if payload is None else json.dumps(payload).encode("utf-8"))
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_order(self, payload: dict[str, Any], *, family: str = "predictions") -> dict[str, Any]:
        path = "portfolio/events/orders" if family == "predictions" else "orders"
        return self._mutation("POST", path, payload, family=family)

    def get_order(self, order_id: str, *, family: str = "predictions") -> dict[str, Any]:
        path = f"portfolio/orders/{order_id}" if family == "predictions" else f"orders/{order_id}"
        return self.perps(path) if family == "perps" else self._get(path, authenticated=True)

    def cancel_order(self, order_id: str, *, family: str = "predictions") -> dict[str, Any]:
        path = f"portfolio/events/orders/{order_id}" if family == "predictions" else f"orders/{order_id}"
        return self._mutation("DELETE", path, family=family)
