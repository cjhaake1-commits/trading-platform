from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..broker_environment import require_alpaca_paper_url, require_oanda_practice_url
from .connectivity import test_oanda_practice


@dataclass(frozen=True)
class PracticeOrderResult:
    broker: str
    ok: bool
    message: str
    details: dict[str, object]


def _request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
    retries: int = 3,
) -> tuple[object, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    last_error: RuntimeError | None = None
    for attempt in range(retries + 1):
        request = Request(url, headers=headers, data=data, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                payload: object = json.loads(raw) if raw else {}
                return payload, {key: value for key, value in response.headers.items()}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < retries:
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
                delay = retry_after if retry_after is not None else min(2.0 ** attempt, 8.0)
                delay += random.uniform(0.0, min(delay * 0.25, 0.25))
                time.sleep(delay)
                continue
            last_error = RuntimeError(f"HTTP {exc.code}: {raw}")
            break
        except URLError as exc:
            last_error = RuntimeError(f"Connection error: {exc.reason}")
            break
    if last_error is not None:
        raise last_error
    raise RuntimeError("broker request failed without response")


def _retry_after_seconds(value: object) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return max(seconds, 0.0)


def _alpaca_credentials() -> tuple[str, str, str]:
    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    base_url = require_alpaca_paper_url(os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"))
    return key, secret, base_url


def _alpaca_headers(key: str, secret: str) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _alpaca_price(value: float) -> str:
    price = Decimal(str(value))
    quantum = Decimal("0.01") if price >= Decimal("1") else Decimal("0.0001")
    return format(price.quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _alpaca_crypto_increment(symbol: str) -> Decimal:
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return Decimal("0.01")
    try:
        asset, _ = _request_json(
            f"{base_url}/v2/assets/{quote(symbol.strip().upper(), safe='')}",
            method="GET",
            headers=_alpaca_headers(key, secret),
        )
        if isinstance(asset, dict) and asset.get("price_increment"):
            return Decimal(str(asset["price_increment"]))
    except RuntimeError:
        pass
    return Decimal("0.01")


def _alpaca_crypto_price(symbol: str, value: float) -> str:
    quantum = _alpaca_crypto_increment(symbol)
    return format(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def submit_alpaca_paper_market_order(
    symbol: str, *, side: str = "buy", notional: float = 1.0, client_order_id: str | None = None
) -> PracticeOrderResult:
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return PracticeOrderResult("alpaca-paper", False, "Missing Alpaca paper credentials", {})
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if notional <= 0:
        raise ValueError("notional must be positive")
    payload: dict[str, object] = {
        "symbol": symbol.strip().upper(),
        "notional": f"{notional:.2f}",
        "side": side,
        "type": "market",
        "time_in_force": "day",
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id
    try:
        response, headers = _request_json(
            f"{base_url}/v2/orders", method="POST", headers=_alpaca_headers(key, secret), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("alpaca-paper", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("alpaca-paper", False, "Unexpected Alpaca response", {})
    return PracticeOrderResult(
        "alpaca-paper",
        True,
        "Submitted Alpaca paper market order",
        {
            "id": response.get("id"),
            "client_order_id": response.get("client_order_id"),
            "symbol": response.get("symbol"),
            "side": response.get("side"),
            "type": response.get("type"),
            "status": response.get("status"),
            "notional": response.get("notional"),
            "filled_qty": response.get("filled_qty"),
            "filled_avg_price": response.get("filled_avg_price"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
        },
    )


def submit_alpaca_paper_extended_hours_limit_order(
    symbol: str,
    *,
    qty: float,
    limit_price: float,
    side: str = "buy",
    client_order_id: str | None = None,
    time_in_force: str = "day",
) -> PracticeOrderResult:
    """Submit an Alpaca Paper 24/5-eligible U.S. equity limit order.

    Alpaca requires limit orders for overnight execution and the extended_hours
    flag. This helper does not weaken the portfolio risk layer and does not claim
    to provide an exchange-native overnight stop; runtime protection is handled
    separately before autonomous use.
    """
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return PracticeOrderResult("alpaca-paper", False, "Missing Alpaca paper credentials", {})
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if qty <= 0 or limit_price <= 0:
        raise ValueError("qty and limit_price must be positive")
    if time_in_force not in {"day", "gtc"}:
        raise ValueError("extended-hours time_in_force must be day or gtc")
    payload: dict[str, object] = {
        "symbol": symbol.strip().upper(),
        "qty": f"{qty:.9f}".rstrip("0").rstrip("."),
        "side": side,
        "type": "limit",
        "limit_price": _alpaca_price(limit_price),
        "time_in_force": time_in_force,
        "extended_hours": True,
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id
    try:
        response, headers = _request_json(
            f"{base_url}/v2/orders", method="POST", headers=_alpaca_headers(key, secret), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("alpaca-paper", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("alpaca-paper", False, "Unexpected Alpaca response", {})
    return PracticeOrderResult(
        "alpaca-paper",
        True,
        "Submitted Alpaca paper 24/5 extended-hours limit order",
        {
            "id": response.get("id"),
            "client_order_id": response.get("client_order_id"),
            "status": response.get("status"),
            "symbol": response.get("symbol"),
            "limit_price": response.get("limit_price"),
            "extended_hours": response.get("extended_hours"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
        },
    )


def submit_alpaca_paper_protected_order(
    symbol: str, *, qty: float, stop_price: float, side: str = "buy", client_order_id: str | None = None
) -> PracticeOrderResult:
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return PracticeOrderResult("alpaca-paper", False, "Missing Alpaca paper credentials", {})
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if qty <= 0 or stop_price <= 0:
        raise ValueError("qty and stop_price must be positive")
    payload: dict[str, object] = {
        "symbol": symbol.strip().upper(),
        "qty": f"{qty:.9f}".rstrip("0").rstrip("."),
        "side": side,
        "type": "market",
        "time_in_force": "day",
        "order_class": "oto",
        "stop_loss": {"stop_price": _alpaca_price(stop_price)},
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id
    try:
        response, headers = _request_json(
            f"{base_url}/v2/orders", method="POST", headers=_alpaca_headers(key, secret), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("alpaca-paper", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("alpaca-paper", False, "Unexpected Alpaca response", {})
    return PracticeOrderResult(
        "alpaca-paper",
        True,
        "Submitted Alpaca paper protected OTO order",
        {
            "id": response.get("id"),
            "client_order_id": response.get("client_order_id"),
            "status": response.get("status"),
            "symbol": response.get("symbol"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
        },
    )


def submit_alpaca_paper_crypto_market_order(
    symbol: str, *, qty: float, side: str = "buy", client_order_id: str | None = None
) -> PracticeOrderResult:
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return PracticeOrderResult("alpaca-crypto-paper", False, "Missing Alpaca paper credentials", {})
    if side not in {"buy", "sell"} or qty <= 0:
        raise ValueError("valid side and positive qty are required")
    payload: dict[str, object] = {
        "symbol": symbol.strip().upper(),
        "qty": f"{qty:.9f}".rstrip("0").rstrip("."),
        "side": side,
        "type": "market",
        "time_in_force": "gtc",
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id
    try:
        response, headers = _request_json(
            f"{base_url}/v2/orders", method="POST", headers=_alpaca_headers(key, secret), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("alpaca-crypto-paper", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("alpaca-crypto-paper", False, "Unexpected Alpaca response", {})
    return PracticeOrderResult(
        "alpaca-crypto-paper",
        True,
        "Submitted Alpaca paper crypto market order",
        {
            "id": response.get("id"),
            "client_order_id": response.get("client_order_id"),
            "status": response.get("status"),
            "symbol": response.get("symbol"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
        },
    )


def submit_alpaca_paper_crypto_stop_limit(
    symbol: str, *, qty: float, stop_price: float, client_order_id: str | None = None
) -> PracticeOrderResult:
    key, secret, base_url = _alpaca_credentials()
    if not key or not secret:
        return PracticeOrderResult("alpaca-crypto-paper", False, "Missing Alpaca paper credentials", {})
    if qty <= 0 or stop_price <= 0:
        raise ValueError("qty and stop_price must be positive")
    rounded_stop = _alpaca_crypto_price(symbol, stop_price)
    rounded_limit = _alpaca_crypto_price(symbol, max(float(rounded_stop) * 0.995, 1e-8))
    payload: dict[str, object] = {
        "symbol": symbol.strip().upper(),
        "qty": f"{qty:.9f}".rstrip("0").rstrip("."),
        "side": "sell",
        "type": "stop_limit",
        "time_in_force": "gtc",
        "stop_price": rounded_stop,
        "limit_price": rounded_limit,
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id
    try:
        response, headers = _request_json(
            f"{base_url}/v2/orders", method="POST", headers=_alpaca_headers(key, secret), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("alpaca-crypto-paper", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("alpaca-crypto-paper", False, "Unexpected Alpaca response", {})
    return PracticeOrderResult(
        "alpaca-crypto-paper",
        True,
        "Submitted Alpaca paper crypto protective stop-limit",
        {
            "id": response.get("id"),
            "client_order_id": response.get("client_order_id"),
            "status": response.get("status"),
            "symbol": response.get("symbol"),
            "stop_price": response.get("stop_price"),
            "limit_price": response.get("limit_price"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
        },
    )


def _oanda_account_id() -> str:
    configured = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
    if configured:
        return configured
    result = test_oanda_practice()
    if not result.ok:
        raise RuntimeError(result.message)
    selected = result.details.get("selected_account_id")
    if not selected:
        raise RuntimeError("Could not determine OANDA practice account ID")
    return str(selected)


def _oanda_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339",
    }


def submit_oanda_practice_market_order(
    symbol: str, *, units: int = 1, stop_price: float | None = None, client_order_id: str | None = None
) -> PracticeOrderResult:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    base_url = require_oanda_practice_url(os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com"))
    if not token:
        return PracticeOrderResult("oanda-practice", False, "Missing OANDA practice token", {})
    if units == 0:
        raise ValueError("units cannot be zero")
    if stop_price is not None and stop_price <= 0:
        raise ValueError("stop_price must be positive")
    account_id = _oanda_account_id()
    instrument = symbol.strip().upper().replace("/", "_")
    order: dict[str, object] = {
        "instrument": instrument,
        "units": str(units),
        "timeInForce": "FOK",
        "type": "MARKET",
        "positionFill": "DEFAULT",
    }
    if stop_price is not None:
        order["stopLossOnFill"] = {"price": str(stop_price), "timeInForce": "GTC"}
    if client_order_id:
        order["clientExtensions"] = {"id": client_order_id, "tag": "autotrader"}
        order["tradeClientExtensions"] = {"id": client_order_id, "tag": "autotrader"}
    payload = {"order": order}
    try:
        response, headers = _request_json(
            f"{base_url}/v3/accounts/{account_id}/orders", method="POST", headers=_oanda_headers(token), body=payload
        )
    except RuntimeError as exc:
        return PracticeOrderResult("oanda-practice", False, str(exc), {"request": payload})
    if not isinstance(response, dict):
        return PracticeOrderResult("oanda-practice", False, "Unexpected OANDA response", {})
    create_tx = response.get("orderCreateTransaction")
    fill_tx = response.get("orderFillTransaction")
    cancel_tx = response.get("orderCancelTransaction")
    return PracticeOrderResult(
        "oanda-practice",
        fill_tx is not None and cancel_tx is None,
        "Submitted OANDA practice market order",
        {
            "last_transaction_id": response.get("lastTransactionID"),
            "order_create_transaction": create_tx,
            "order_fill_transaction": fill_tx,
            "order_cancel_transaction": cancel_tx,
            "related_transaction_ids": response.get("relatedTransactionIDs"),
            "request_id": headers.get("RequestID") or headers.get("requestid"),
        },
    )
