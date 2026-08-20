from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from autotrader.capital_allocations import METALS_PAPER_CAPITAL

ALPACA_PAPER_ENV = "paper"
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
METALS_UNIVERSE = ("GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL")


class AlpacaMetalsConfigurationError(ValueError):
    """Raised when the Alpaca metals adapter is not safely configured."""


class AlpacaMetalsSafetyError(RuntimeError):
    """Raised when an unapproved paper-order action is attempted."""


JsonRequester = Callable[
    [str, str, dict[str, str], dict[str, object] | None, float],
    tuple[object, dict[str, str]],
]


@dataclass(frozen=True)
class AlpacaMetalsAccountSummary:
    environment: str
    account_id: str | None
    status: str | None
    currency: str | None
    equity: float | None
    cash: float | None
    buying_power: float | None
    metals_allocation_cap: float = METALS_PAPER_CAPITAL

    def as_dict(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "account_id": self.account_id,
            "status": self.status,
            "currency": self.currency,
            "equity": self.equity,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "metals_allocation_cap": self.metals_allocation_cap,
        }


@dataclass(frozen=True)
class AlpacaApprovedMetalsOrder:
    symbol: str
    side: str
    quantity: float
    stop_price: float
    target_price: float | None
    client_order_id: str
    risk_approved: bool


@dataclass(frozen=True)
class AlpacaMetalsOrderResult:
    ok: bool
    order_id: str | None
    message: str
    fill_price: float | None = None
    fees_costs: float | None = None


def _request_json(
    url: str,
    method: str,
    headers: dict[str, str],
    body: dict[str, object] | None,
    timeout: float,
) -> tuple[object, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload: object = json.loads(raw) if raw else {}
            return payload, {key: value for key, value in response.headers.items()}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Alpaca paper HTTP {exc.code}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Alpaca paper connection error: {exc.reason}") from exc


class AlpacaMetalsPaperAdapter:
    """Hard-locked Alpaca PAPER adapter for approved metals exchange-traded products."""

    def __init__(
        self,
        *,
        environment: str,
        api_key: str,
        api_secret: str,
        request_json: JsonRequester = _request_json,
    ) -> None:
        normalized = environment.strip().lower()
        if normalized != ALPACA_PAPER_ENV:
            raise AlpacaMetalsConfigurationError("Alpaca metals adapter is locked to ALPACA_ENV=paper")
        if not api_key.strip() or not api_secret.strip():
            raise AlpacaMetalsConfigurationError("Missing Alpaca paper credentials")
        self.environment = normalized
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        self._request_json = request_json

    @classmethod
    def from_env(cls, *, request_json: JsonRequester = _request_json) -> AlpacaMetalsPaperAdapter:
        return cls(
            environment=os.getenv("ALPACA_ENV", "paper"),
            api_key=os.getenv("ALPACA_PAPER_API_KEY", ""),
            api_secret=os.getenv("ALPACA_PAPER_SECRET_KEY", ""),
            request_json=request_json,
        )

    @property
    def base_url(self) -> str:
        return ALPACA_PAPER_BASE_URL

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        if self.environment != ALPACA_PAPER_ENV or self.base_url != ALPACA_PAPER_BASE_URL:
            raise AlpacaMetalsConfigurationError("Alpaca metals requests are locked to the paper endpoint")
        try:
            payload, _ = self._request_json(f"{ALPACA_PAPER_BASE_URL}{path}", method, self._headers(), body, 15.0)
        except RuntimeError as exc:
            message = str(exc).replace(self._api_key, "<redacted>").replace(self._api_secret, "<redacted>")
            raise RuntimeError(message) from exc
        return payload

    def account_summary(self) -> AlpacaMetalsAccountSummary:
        payload = self._request("GET", "/v2/account")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Alpaca paper account response")
        return AlpacaMetalsAccountSummary(
            environment=self.environment,
            account_id=_string(payload.get("id")),
            status=_string(payload.get("status")),
            currency=_string(payload.get("currency")),
            equity=_float(payload.get("equity")),
            cash=_float(payload.get("cash")),
            buying_power=_float(payload.get("buying_power")),
        )

    def asset(self, symbol: str) -> dict[str, object] | None:
        canonical = symbol.strip().upper()
        if canonical not in METALS_UNIVERSE:
            return None
        try:
            payload = self._request("GET", f"/v2/assets/{quote(canonical, safe='')}")
        except RuntimeError:
            return None
        return payload if isinstance(payload, dict) else None

    def is_tradable(self, symbol: str) -> bool:
        asset = self.asset(symbol)
        return bool(asset and asset.get("status") == "active" and asset.get("tradable") is True)

    def tradable_metals(self) -> tuple[str, ...]:
        return tuple(symbol for symbol in METALS_UNIVERSE if self.is_tradable(symbol))

    def submit_order(self, order: AlpacaApprovedMetalsOrder) -> AlpacaMetalsOrderResult:
        if not order.risk_approved:
            raise AlpacaMetalsSafetyError("Alpaca metals order requires deterministic risk approval")
        symbol = order.symbol.strip().upper()
        if symbol not in METALS_UNIVERSE:
            raise AlpacaMetalsSafetyError("Symbol is outside the approved metals universe")
        if not self.is_tradable(symbol):
            raise AlpacaMetalsSafetyError("Symbol is not currently active and tradable on Alpaca paper")
        if order.side.lower() not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order.quantity <= 0 or order.stop_price <= 0:
            raise ValueError("positive quantity and explicit stop are required")

        payload: dict[str, object] = {
            "symbol": symbol,
            "qty": f"{order.quantity:.9f}".rstrip("0").rstrip("."),
            "side": order.side.lower(),
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket" if order.target_price is not None else "oto",
            "stop_loss": {"stop_price": f"{order.stop_price:.2f}"},
            "client_order_id": order.client_order_id[:48],
        }
        if order.target_price is not None:
            payload["take_profit"] = {"limit_price": f"{order.target_price:.2f}"}
        try:
            response = self._request("POST", "/v2/orders", payload)
        except RuntimeError as exc:
            return AlpacaMetalsOrderResult(False, None, str(exc))
        if not isinstance(response, dict):
            return AlpacaMetalsOrderResult(False, None, "Unexpected Alpaca paper order response")
        order_id = _string(response.get("id"))
        return AlpacaMetalsOrderResult(
            ok=bool(order_id),
            order_id=order_id,
            message="Alpaca metals paper order accepted" if order_id else "Alpaca response omitted order id",
            fill_price=_float(response.get("filled_avg_price")),
        )


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
