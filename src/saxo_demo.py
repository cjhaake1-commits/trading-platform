import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SaxoDemoConfig:
    app_key: str
    app_secret: str
    redirect_uri: str = "http://localhost:8501"
    base_url: str = "https://gateway.saxobank.com/sim/openapi"


class SaxoDemoClient:
    """Saxo OpenAPI simulation client. Live endpoints are intentionally rejected."""

    def __init__(self, access_token: str | None = None) -> None:
        if os.getenv("SAXO_ENV", "sim").lower() not in {"sim", "simulation", "demo"}:
            raise RuntimeError("Safety lock: only Saxo simulation mode is allowed.")

        app_key = os.getenv("SAXO_APP_KEY")
        app_secret = os.getenv("SAXO_APP_SECRET")
        if not app_key or not app_secret:
            raise RuntimeError("Set SAXO_APP_KEY and SAXO_APP_SECRET for demo mode.")

        self.config = SaxoDemoConfig(
            app_key=app_key,
            app_secret=app_secret,
            redirect_uri=os.getenv("SAXO_REDIRECT_URI", "http://localhost:8501"),
        )
        self.access_token = access_token or os.getenv("SAXO_ACCESS_TOKEN")
        self.headers = {"Content-Type": "application/json"}
        if self.access_token:
            self.headers["Authorization"] = f"Bearer {self.access_token}"

    @property
    def authorization_url(self) -> str:
        return (
            "https://sim.logonvalidation.net/authorize"
            f"?response_type=code&client_id={self.config.app_key}"
            f"&redirect_uri={self.config.redirect_uri}"
        )

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = requests.post(
            "https://sim.logonvalidation.net/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.config.app_key,
                "client_secret": self.config.app_secret,
                "redirect_uri": self.config.redirect_uri,
            },
            timeout=20,
        )
        response.raise_for_status()
        token = response.json()
        self.access_token = token["access_token"]
        self.headers["Authorization"] = f"Bearer {self.access_token}"
        return token

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.access_token:
            raise RuntimeError("Authenticate with the Saxo simulation account first.")
        response = requests.request(
            method,
            f"{self.config.base_url}{path}",
            headers=self.headers,
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def client_accounts(self) -> Any:
        return self._request("GET", "/cs/v1/accounts")

    def positions(self) -> Any:
        return self._request("GET", "/port/v1/positions")

    def quote(self, uic: int, asset_type: str = "FxSpot") -> Any:
        return self._request(
            "GET",
            "/trade/v1/infoprices",
            params={"Uic": uic, "AssetType": asset_type, "FieldGroups": "DisplayAndFormat"},
        )

    def market_order(
        self,
        account_key: str,
        uic: int,
        asset_type: str,
        amount: Decimal,
        buy_sell: str,
    ) -> Any:
        side = buy_sell.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("buy_sell must be BUY or SELL.")
        if amount <= 0:
            raise ValueError("Paper order amount must be positive.")

        return self._request(
            "POST",
            "/trade/v2/orders",
            json={
                "AccountKey": account_key,
                "Uic": uic,
                "AssetType": asset_type,
                "Amount": float(amount),
                "BuySell": side,
                "OrderType": "Market",
                "ManualOrder": True,
                "OrderPrice": 0,
                "TimeInForce": {"DurationType": "DayOrder"},
            },
        )
