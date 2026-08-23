"""Separate, Demo-only Kalshi execution transport with conservative gates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .auth import KalshiAuthReference
from .config import KalshiConfig


@dataclass(frozen=True)
class DemoOrderDecision:
    approved: bool
    reason: str
    client_order_id: str | None = None


class KalshiDemoExecutionClient:
    """Mutation-capable only when explicit Demo gate is enabled; never production."""

    def __init__(self, config: KalshiConfig | None = None, *, timeout: float = 10.0):
        self.config = config or KalshiConfig.from_env()
        if self.config.environment != "demo":
            raise ValueError("Kalshi Demo execution rejects non-Demo environment")
        self.timeout = timeout
        self.auth = KalshiAuthReference.from_config(self.config)

    def _base(self, family: str) -> str:
        return (self.config.perps_rest_url if family == "perps" else self.config.predictions_rest_url).rstrip("/")

    def _request(self, method: str, path: str, *, family: str = "predictions", body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.demo_trading_enabled:
            raise RuntimeError("Kalshi Demo execution gate is disabled")
        url = self._base(family) + "/" + path.lstrip("/")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.auth.sign(method, url))
        request = Request(url, method=method.upper(), headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError):
            raise

    def create_prediction_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "portfolio/events/orders", body=order)

    def get_prediction_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"portfolio/orders/{order_id}")

    def cancel_prediction_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"portfolio/orders/{order_id}")

    def create_perps_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "orders", family="perps", body=order)

    def get_perps_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"orders/{order_id}", family="perps")

    def cancel_perps_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"orders/{order_id}", family="perps")


def qualify_demo_order(*, config: KalshiConfig, market_open: bool, fresh: bool, valid_price: bool,
                       valid_tick: bool, liquidity: bool, spread_ok: bool, fee_known: bool,
                       expected_edge: float, capital_available: float, required_capital: float,
                       duplicate: bool = False) -> DemoOrderDecision:
    checks = (("Demo gate", config.demo_trading_enabled), ("market closed", market_open),
              ("data stale", fresh), ("invalid price", valid_price), ("invalid tick", valid_tick),
              ("insufficient liquidity", liquidity), ("spread too wide", spread_ok),
              ("fee unknown", fee_known), ("non-positive edge", expected_edge > 0),
              ("capital constrained", capital_available >= required_capital), ("duplicate exposure", not duplicate))
    for reason, passed in checks:
        if not passed:
            return DemoOrderDecision(False, reason)
    return DemoOrderDecision(True, "all Demo execution gates passed")
