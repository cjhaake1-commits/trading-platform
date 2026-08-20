from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from autotrader.capital_allocations import INTERNATIONAL_SIM_CAPITAL

SAXO_SIM_ENV = "sim"
SAXO_SIM_BASE_URL = "https://gateway.saxobank.com/sim/openapi"


class SaxoConfigurationError(ValueError):
    """Raised when the fail-closed Saxo SIM configuration is invalid."""


class SaxoReadOnlyError(RuntimeError):
    """Raised when a caller attempts a write through the read-only adapter."""


@dataclass(frozen=True)
class SaxoSafeAccountSummary:
    environment: str
    client_id: str | None
    default_account_id: str | None
    default_currency: str | None
    accounts: tuple[dict[str, object], ...]
    balance_currency: str | None
    cash_balance: float | None
    cash_available_for_trading: float | None
    total_value: float | None
    international_allocation_cap: float = INTERNATIONAL_SIM_CAPITAL
    read_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "client_id": self.client_id,
            "default_account_id": self.default_account_id,
            "default_currency": self.default_currency,
            "accounts": [dict(account) for account in self.accounts],
            "balance_currency": self.balance_currency,
            "cash_balance": self.cash_balance,
            "cash_available_for_trading": self.cash_available_for_trading,
            "total_value": self.total_value,
            "international_allocation_cap": self.international_allocation_cap,
            "read_only": self.read_only,
        }


JsonGetter = Callable[[str, dict[str, str], float], tuple[dict[str, object], dict[str, str]]]
JsonRequester = Callable[
    [str, str, dict[str, str], dict[str, object] | None, float],
    tuple[dict[str, object], dict[str, str]],
]


def _get_json(
    url: str,
    headers: dict[str, str],
    timeout: float = 10.0,
) -> tuple[dict[str, object], dict[str, str]]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            if not isinstance(payload, dict):
                raise RuntimeError("Unexpected non-object response from Saxo SIM")
            return payload, {key: value for key, value in response.headers.items()}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Saxo SIM HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Saxo SIM connection error: {exc.reason}") from exc


def _request_json(
    url: str,
    method: str,
    headers: dict[str, str],
    body: dict[str, object] | None,
    timeout: float,
) -> tuple[dict[str, object], dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise RuntimeError("Unexpected non-object response from Saxo SIM")
            return payload, {key: value for key, value in response.headers.items()}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Saxo SIM HTTP {exc.code}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Saxo SIM connection error: {exc.reason}") from exc


@dataclass(frozen=True)
class SaxoApprovedOrder:
    account_key: str
    uic: int
    asset_type: str
    side: str
    quantity: float
    stop_price: float
    external_reference: str
    risk_approved: bool


@dataclass(frozen=True)
class SaxoOrderResult:
    ok: bool
    order_id: str | None
    message: str
    fill_price: float | None = None
    estimated_costs: float | None = None


class SaxoSimAdapter:
    """Fail-closed adapter for Saxo OpenAPI's simulation host.

    Portfolio access is read-only. The order boundary accepts only structured
    tickets marked as approved by the deterministic international risk service.
    """

    def __init__(
        self,
        *,
        environment: str,
        access_token: str,
        get_json: JsonGetter = _get_json,
        request_json: JsonRequester = _request_json,
    ) -> None:
        normalized_environment = environment.strip().lower()
        if normalized_environment != SAXO_SIM_ENV:
            raise SaxoConfigurationError("Saxo adapter is locked to SAXO_ENV=sim")
        if not access_token.strip():
            raise SaxoConfigurationError("Missing SAXO_ACCESS_TOKEN")

        self.environment = normalized_environment
        self._access_token = access_token.strip()
        self._get_json = get_json
        self._request_json = request_json

    @classmethod
    def from_env(
        cls,
        *,
        get_json: JsonGetter = _get_json,
        request_json: JsonRequester = _request_json,
    ) -> SaxoSimAdapter:
        return cls(
            environment=os.getenv("SAXO_ENV", ""),
            access_token=os.getenv("SAXO_ACCESS_TOKEN", ""),
            get_json=get_json,
            request_json=request_json,
        )

    @property
    def base_url(self) -> str:
        return SAXO_SIM_BASE_URL

    @property
    def international_allocation_cap(self) -> float:
        return INTERNATIONAL_SIM_CAPITAL

    def _safe_error(self, exc: RuntimeError) -> RuntimeError:
        message = str(exc).replace(self._access_token, "<redacted>")
        return RuntimeError(message)

    def _read(self, path: str) -> dict[str, object]:
        if not path.startswith("/port/"):
            raise SaxoReadOnlyError("Saxo SIM adapter permits portfolio reads only")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        try:
            payload, _ = self._get_json(f"{self.base_url}{path}", headers, 10.0)
        except RuntimeError as exc:
            raise self._safe_error(exc) from exc
        return payload

    def account_summary(self) -> SaxoSafeAccountSummary:
        client = self._read("/port/v1/clients/me")
        accounts_payload = self._read("/port/v1/accounts/me")
        balance = self._read("/port/v1/balances/me")

        raw_accounts = accounts_payload.get("Data")
        accounts: list[dict[str, object]] = []
        if isinstance(raw_accounts, list):
            for account in raw_accounts:
                if not isinstance(account, dict):
                    continue
                accounts.append(
                    {
                        "account_id": account.get("AccountId"),
                        "currency": account.get("Currency"),
                        "active": account.get("Active"),
                        "account_type": account.get("AccountType"),
                    }
                )

        return SaxoSafeAccountSummary(
            environment=self.environment,
            client_id=_optional_string(client.get("ClientId")),
            default_account_id=_optional_string(client.get("DefaultAccountId")),
            default_currency=_optional_string(client.get("DefaultCurrency")),
            accounts=tuple(accounts),
            balance_currency=_optional_string(balance.get("Currency")),
            cash_balance=_optional_float(balance.get("CashBalance")),
            cash_available_for_trading=_optional_float(balance.get("CashAvailableForTrading")),
            total_value=_optional_float(balance.get("TotalValue")),
        )

    def submit_order(self, order: SaxoApprovedOrder) -> SaxoOrderResult:
        if self.environment != SAXO_SIM_ENV or self.base_url != SAXO_SIM_BASE_URL:
            raise SaxoConfigurationError("Saxo order submission is locked to the SIM endpoint")
        if not order.risk_approved:
            raise SaxoReadOnlyError("Saxo SIM order requires deterministic risk approval")
        if order.side.lower() not in {"buy", "sell"}:
            raise ValueError("Saxo side must be buy or sell")
        if order.quantity <= 0 or order.stop_price <= 0:
            raise ValueError("Saxo quantity and protective stop must be positive")
        if not order.account_key.strip() or order.uic <= 0:
            raise ValueError("Saxo AccountKey and positive Uic are required")

        buy_sell = order.side.title()
        closing_side = "Sell" if buy_sell == "Buy" else "Buy"
        payload: dict[str, object] = {
            "AccountKey": order.account_key,
            "Amount": order.quantity,
            "AssetType": order.asset_type,
            "BuySell": buy_sell,
            "ExternalReference": order.external_reference[:50],
            "ManualOrder": False,
            "OrderDuration": {"DurationType": "DayOrder"},
            "OrderType": "Market",
            "Uic": order.uic,
            "Orders": [
                {
                    "AccountKey": order.account_key,
                    "Amount": order.quantity,
                    "AssetType": order.asset_type,
                    "BuySell": closing_side,
                    "ManualOrder": False,
                    "OrderDuration": {"DurationType": "GoodTillCancel"},
                    "OrderPrice": order.stop_price,
                    "OrderType": "Stop",
                    "Uic": order.uic,
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response, _ = self._request_json(
                f"{SAXO_SIM_BASE_URL}/trade/v2/orders",
                "POST",
                headers,
                payload,
                15.0,
            )
        except RuntimeError as exc:
            return SaxoOrderResult(False, None, str(self._safe_error(exc)))

        error = response.get("ErrorInfo")
        if error:
            return SaxoOrderResult(False, None, f"Saxo SIM rejected order: {_safe_error_message(error)}")
        order_id = _optional_string(response.get("OrderId"))
        return SaxoOrderResult(
            ok=bool(order_id),
            order_id=order_id,
            message="Saxo SIM paper order accepted" if order_id else "Saxo SIM response omitted OrderId",
            fill_price=_optional_float(response.get("Price") or response.get("OrderPrice")),
            estimated_costs=None,
        )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _safe_error_message(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("Message") or value.get("ErrorCode") or "order rejected")
    return "order rejected"
