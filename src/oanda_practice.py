import os
from dataclasses import dataclass
from decimal import Decimal

import requests
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade: Decimal = Decimal("0.005")
    daily_loss_stop: Decimal = Decimal("0.02")
    max_open_positions: int = 3


class OandaPracticeClient:
    def __init__(self) -> None:
        env = os.getenv("OANDA_ENV", "practice").lower()
        if env != "practice":
            raise RuntimeError("Safety lock: only OANDA practice environment is allowed.")

        self.account_id = os.environ["OANDA_ACCOUNT_ID"]
        token = os.environ["OANDA_API_TOKEN"]
        self.base_url = "https://api-fxpractice.oanda.com/v3"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs):
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self.headers,
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def account_summary(self):
        return self._request("GET", f"/accounts/{self.account_id}/summary")

    def price(self, instrument: str):
        return self._request(
            "GET",
            f"/accounts/{self.account_id}/pricing",
            params={"instruments": instrument},
        )

    def open_trades(self):
        return self._request("GET", f"/accounts/{self.account_id}/openTrades")

    def market_order(self, instrument: str, units: int, stop_loss_price: str):
        if not stop_loss_price:
            raise ValueError("Every paper entry requires an explicit stop-loss price.")
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": str(stop_loss_price)},
            }
        }
        return self._request(
            "POST",
            f"/accounts/{self.account_id}/orders",
            json=payload,
        )


def position_units(equity: Decimal, entry: Decimal, stop: Decimal, limits: RiskLimits) -> int:
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("Stop must differ from entry price.")
    risk_budget = equity * limits.risk_per_trade
    units = int(risk_budget / distance)
    if units < 1:
        raise ValueError("Calculated position is below one unit.")
    return units
