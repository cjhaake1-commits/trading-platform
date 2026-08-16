from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ConnectivityResult:
    broker: str
    ok: bool
    message: str
    details: dict[str, object]


def _get_json(url: str, headers: dict[str, str], timeout: float = 10.0) -> tuple[dict, dict]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            response_headers = {key: value for key, value in response.headers.items()}
            return payload, response_headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Connection error: {exc.reason}") from exc


def test_alpaca_paper() -> ConnectivityResult:
    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    base_url = os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")

    if not key or not secret:
        return ConnectivityResult(
            broker="alpaca-paper",
            ok=False,
            message="Missing Alpaca paper credentials",
            details={"required_env": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"]},
        )

    try:
        payload, headers = _get_json(
            f"{base_url}/v2/account",
            {
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )
    except RuntimeError as exc:
        return ConnectivityResult("alpaca-paper", False, str(exc), {})

    return ConnectivityResult(
        broker="alpaca-paper",
        ok=True,
        message="Authenticated to Alpaca paper Trading API",
        details={
            "account_id": payload.get("id"),
            "status": payload.get("status"),
            "currency": payload.get("currency"),
            "equity": payload.get("equity"),
            "cash": payload.get("cash"),
            "buying_power": payload.get("buying_power"),
            "request_id": headers.get("X-Request-ID") or headers.get("x-request-id"),
            "base_url": base_url,
        },
    )


def test_oanda_practice() -> ConnectivityResult:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    base_url = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")

    if not token:
        return ConnectivityResult(
            broker="oanda-practice",
            ok=False,
            message="Missing OANDA practice token",
            details={"required_env": ["OANDA_PRACTICE_TOKEN"]},
        )

    try:
        accounts_payload, headers = _get_json(
            f"{base_url}/v3/accounts",
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    except RuntimeError as exc:
        return ConnectivityResult("oanda-practice", False, str(exc), {})

    accounts = accounts_payload.get("accounts") or []
    account_ids = [account.get("id") for account in accounts if account.get("id")]
    configured = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
    selected = configured or (account_ids[0] if account_ids else None)

    details: dict[str, object] = {
        "account_ids": account_ids,
        "selected_account_id": selected,
        "request_id": headers.get("RequestID") or headers.get("requestid"),
        "base_url": base_url,
    }

    if selected:
        try:
            account_payload, account_headers = _get_json(
                f"{base_url}/v3/accounts/{selected}/summary",
                {"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            account = account_payload.get("account") or {}
            details.update(
                {
                    "currency": account.get("currency"),
                    "balance": account.get("balance"),
                    "NAV": account.get("NAV"),
                    "margin_available": account.get("marginAvailable"),
                    "open_trade_count": account.get("openTradeCount"),
                    "account_request_id": account_headers.get("RequestID")
                    or account_headers.get("requestid"),
                }
            )
        except RuntimeError as exc:
            return ConnectivityResult(
                broker="oanda-practice",
                ok=False,
                message=f"Token authenticated but account summary failed: {exc}",
                details=details,
            )

    return ConnectivityResult(
        broker="oanda-practice",
        ok=True,
        message="Authenticated to OANDA fxTrade Practice API",
        details=details,
    )
