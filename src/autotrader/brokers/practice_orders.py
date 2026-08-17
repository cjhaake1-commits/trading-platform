from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
) -> tuple[object, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload: object = json.loads(raw) if raw else {}
            response_headers = {key: value for key, value in response.headers.items()}
            return payload, response_headers
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Connection error: {exc.reason}") from exc


def _alpaca_credentials() -> tuple[str, str, str]:
    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    base_url = os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
    return key, secret, base_url


def _alpaca_headers(key: str, secret: str) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _alpaca_price(value: float) -> str:
    """Format equity/ETF order prices to Alpaca-valid minimum increments.

    Alpaca accepts two decimals for prices at or above $1.00 and four decimals
    for prices below $1.00. Use Decimal to avoid binary-float artifacts.
    """
    price = Decimal(str(value))
    quantum = Decimal("0.01") if price >= Decimal("1") else Decimal("0.0001")
    rounded = price.quantize(quantum, rounding=ROUND_HALF_UP)
    return format(rounded, "f")


def submit_alpaca_paper_market_order(
    symbol: str,
    *,
    side: str = "buy",
    notional: float = 1.0,
    client_order_id: str | None = None,
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
            f"{base_url}/v2/orders",
            method="POST",
            headers=_alpaca_headers(key, secret),
            body=payload,
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


def submit_alpaca_paper_protected_order(
    symbol: str,
    *,
    qty: float,
    stop_price: float,
    side: str = "buy",
    client_order_id: str | None = None,
) -> PracticeOrderResult:
    """Submit an Alpaca paper OTO order with a broker-side stop-loss leg."""
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
            f"{base_url}/v2/orders",
            method="POST",
            headers=_alpaca_headers(key, secret),
            body=payload,
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


def _oanda_credentials() -> tuple[str, str, str]:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    base_url = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")
    return token, base_url, _oanda_account_id() if token else ""


def _oanda_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339",
    }


def submit_oanda_practice_market_order(
    symbol: str,
    *,
    units: int = 1,
    stop_price: float | None = None,
    client_order_id: str | None = None,
) -> PracticeOrderResult:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    base_url = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")
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
            f"{base_url}/v3/accounts/{account_id}/orders",
            method="POST",
            headers=_oanda_headers(token),
            body=payload,
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
