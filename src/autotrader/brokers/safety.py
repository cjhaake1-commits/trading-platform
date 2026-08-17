from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .practice_orders import _oanda_account_id


@dataclass(frozen=True)
class BrokerSafetyResult:
    broker: str
    ok: bool
    message: str
    details: dict[str, object]


def _request(url: str, *, method: str, headers: dict[str, str], body: dict[str, object] | None = None, timeout: float = 15.0) -> tuple[object, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload: object = json.loads(raw) if raw else {}
            return payload, {key: value for key, value in response.headers.items()}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Connection error: {exc.reason}") from exc


def _alpaca_auth() -> tuple[str, str, str]:
    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    base = os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
    if not key or not secret:
        raise RuntimeError("Missing Alpaca paper credentials")
    return key, secret, base


def _alpaca_headers(key: str, secret: str) -> dict[str, str]:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json", "Content-Type": "application/json"}


def _alpaca_api_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace("_", "")


def _canonical_ledger_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("_", "/")
    if "/" in normalized:
        return normalized
    for quote_currency in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote_currency) and len(normalized) > len(quote_currency):
            base = normalized[:-len(quote_currency)]
            if base in {"BTC", "ETH", "LTC", "BCH", "AAVE", "LINK", "UNI", "AVAX", "DOT", "SOL"}:
                return f"{base}/{quote_currency}"
    return normalized


def _clear_flat_ledger_symbol(symbol: str, ledger_path: str | Path) -> bool:
    from ..portfolio_ledger import PortfolioLedger
    path = Path(ledger_path)
    if not path.exists():
        return False
    ledger = PortfolioLedger(path)
    loaded = ledger.load_portfolio()
    if loaded is None:
        return False
    portfolio, peak = loaded
    normalized = _canonical_ledger_symbol(symbol)
    if normalized not in portfolio.positions:
        return False
    del portfolio.positions[normalized]
    ledger.save_portfolio(portfolio, peak_equity=peak)
    return True


def alpaca_open_positions() -> BrokerSafetyResult:
    key, secret, base = _alpaca_auth()
    payload, headers = _request(f"{base}/v2/positions", method="GET", headers=_alpaca_headers(key, secret))
    positions = payload if isinstance(payload, list) else []
    return BrokerSafetyResult("alpaca-paper", True, "Fetched Alpaca paper open positions", {"positions": positions, "request_id": headers.get("X-Request-ID") or headers.get("x-request-id")})


def cancel_alpaca_open_orders_for_symbol(symbol: str) -> BrokerSafetyResult:
    key, secret, base = _alpaca_auth()
    api_symbol = _alpaca_api_symbol(symbol)
    query = urlencode({"status": "open", "symbols": api_symbol, "nested": "true", "limit": 500})
    payload, _ = _request(f"{base}/v2/orders?{query}", method="GET", headers=_alpaca_headers(key, secret))
    orders = payload if isinstance(payload, list) else []
    cancelled: list[str] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        order_id = order.get("id")
        if not order_id or _alpaca_api_symbol(str(order.get("symbol") or "")) != api_symbol:
            continue
        try:
            _request(f"{base}/v2/orders/{quote(str(order_id), safe='')}", method="DELETE", headers=_alpaca_headers(key, secret))
        except RuntimeError as exc:
            if "HTTP 404:" not in str(exc) and "HTTP 422:" not in str(exc):
                raise
        else:
            cancelled.append(str(order_id))
    return BrokerSafetyResult("alpaca-paper", True, "Cancelled Alpaca paper open orders for symbol", {"symbol": _canonical_ledger_symbol(symbol), "cancelled_order_ids": cancelled})


def close_alpaca_position(symbol: str, *, qty: float | None = None, percentage: float | None = None, cancel_open_orders: bool = True, ledger_path: str | Path = "var/autotrader/portfolio.db") -> BrokerSafetyResult:
    if qty is not None and percentage is not None:
        raise ValueError("specify qty or percentage, not both")
    if qty is not None and qty <= 0:
        raise ValueError("qty must be positive")
    if percentage is not None and not 0 < percentage <= 100:
        raise ValueError("percentage must be in (0, 100]")
    key, secret, base = _alpaca_auth()
    canonical = _canonical_ledger_symbol(symbol)
    api_symbol = _alpaca_api_symbol(symbol)
    cancelled: list[str] = []
    full_close = qty is None and percentage is None
    if cancel_open_orders and full_close:
        cancel_result = cancel_alpaca_open_orders_for_symbol(api_symbol)
        cancelled = list(cancel_result.details.get("cancelled_order_ids", []))
    params: dict[str, object] = {}
    if qty is not None:
        params["qty"] = qty
    if percentage is not None:
        params["percentage"] = percentage
    suffix = f"?{urlencode(params)}" if params else ""
    payload, headers = _request(f"{base}/v2/positions/{quote(api_symbol, safe='')}{suffix}", method="DELETE", headers=_alpaca_headers(key, secret))

    still_open = False
    if full_close:
        positions = alpaca_open_positions().details.get("positions", [])
        if isinstance(positions, list):
            still_open = any(isinstance(row, dict) and _alpaca_api_symbol(str(row.get("symbol") or "")) == api_symbol and abs(float(row.get("qty", 0) or 0)) > 1e-12 for row in positions)
    ledger_cleared = False if still_open or not full_close else _clear_flat_ledger_symbol(canonical, ledger_path)
    return BrokerSafetyResult(
        "alpaca-paper",
        not still_open,
        "Submitted Alpaca paper position close" if not still_open else "Alpaca position close submitted but position remains open",
        {"order": payload, "cancelled_open_order_ids": cancelled, "position_still_open": still_open, "ledger_position_cleared": ledger_cleared, "request_id": headers.get("X-Request-ID") or headers.get("x-request-id")},
    )


def flatten_alpaca_account(*, cancel_orders: bool = True) -> BrokerSafetyResult:
    key, secret, base = _alpaca_auth()
    query = urlencode({"cancel_orders": str(cancel_orders).lower()})
    payload, headers = _request(f"{base}/v2/positions?{query}", method="DELETE", headers=_alpaca_headers(key, secret))
    return BrokerSafetyResult("alpaca-paper", True, "Submitted Alpaca paper emergency flatten", {"results": payload, "cancel_orders": cancel_orders, "request_id": headers.get("X-Request-ID") or headers.get("x-request-id")})


def _oanda_auth() -> tuple[str, str, str]:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    base = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")
    if not token:
        raise RuntimeError("Missing OANDA practice token")
    return token, base, _oanda_account_id()


def _oanda_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json", "Accept-Datetime-Format": "RFC3339"}


def oanda_open_positions() -> BrokerSafetyResult:
    token, base, account_id = _oanda_auth()
    payload, headers = _request(f"{base}/v3/accounts/{account_id}/openPositions", method="GET", headers=_oanda_headers(token))
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected OANDA open-position response")
    return BrokerSafetyResult("oanda-practice", True, "Fetched OANDA practice open positions", {"positions": payload.get("positions", []), "last_transaction_id": payload.get("lastTransactionID"), "request_id": headers.get("RequestID") or headers.get("requestid")})


def close_oanda_position(symbol: str, *, long_units: str = "ALL", short_units: str = "ALL", ledger_path: str | Path = "var/autotrader/portfolio.db") -> BrokerSafetyResult:
    token, base, account_id = _oanda_auth()
    instrument = symbol.strip().upper().replace("/", "_")
    payload, headers = _request(f"{base}/v3/accounts/{account_id}/positions/{instrument}/close", method="PUT", headers=_oanda_headers(token), body={"longUnits": str(long_units), "shortUnits": str(short_units)})
    positions = oanda_open_positions().details.get("positions", [])
    normalized = instrument.replace("_", "/")
    still_open = False
    if isinstance(positions, list):
        for position in positions:
            if not isinstance(position, dict):
                continue
            if str(position.get("instrument") or "").replace("_", "/").upper() != normalized:
                continue
            long = position.get("long") if isinstance(position.get("long"), dict) else {}
            short = position.get("short") if isinstance(position.get("short"), dict) else {}
            if abs(float(long.get("units", 0) or 0) + float(short.get("units", 0) or 0)) > 1e-12:
                still_open = True
                break
    ledger_cleared = False if still_open else _clear_flat_ledger_symbol(normalized, ledger_path)
    return BrokerSafetyResult("oanda-practice", not still_open, "Submitted OANDA practice position close" if not still_open else "OANDA position remains open", {"result": payload, "position_still_open": still_open, "ledger_position_cleared": ledger_cleared, "request_id": headers.get("RequestID") or headers.get("requestid")})


def flatten_oanda_account() -> BrokerSafetyResult:
    positions_result = oanda_open_positions()
    positions = positions_result.details.get("positions", [])
    results: list[dict[str, object]] = []
    failures: list[str] = []
    if not isinstance(positions, list):
        positions = []
    for position in positions:
        if not isinstance(position, dict) or not position.get("instrument"):
            continue
        instrument = str(position["instrument"])
        try:
            result = close_oanda_position(instrument)
            results.append({"instrument": instrument, "ok": result.ok, "details": result.details})
            if not result.ok:
                failures.append(f"{instrument}: position remains open")
        except RuntimeError as exc:
            failures.append(f"{instrument}: {exc}")
    return BrokerSafetyResult("oanda-practice", not failures, "Submitted OANDA practice emergency flatten" if not failures else "OANDA flatten had failures", {"results": results, "failures": failures})
