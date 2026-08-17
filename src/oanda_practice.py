import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load the normal project env file first. For recovery/compatibility with the
# existing VM setup, also read .env.save if present. python-dotenv parses the
# file as data; it does not execute stray shell lines.
load_dotenv()
_env_save = Path(__file__).resolve().parents[1] / ".env.save"
if _env_save.exists():
    load_dotenv(_env_save, override=False)


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade: Decimal = Decimal("0.005")
    daily_loss_stop: Decimal = Decimal("0.02")
    max_open_positions: int = 3


class OandaPracticeClient:
    def __init__(self) -> None:
        env = os.getenv("OANDA_ENV", "practice").strip().lower()
        if env != "practice":
            raise RuntimeError("Safety lock: only OANDA practice environment is allowed.")

        token = (
            os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
            or os.getenv("OANDA_API_TOKEN", "").strip()
        )
        if not token:
            raise RuntimeError(
                "Missing OANDA practice token. Set OANDA_PRACTICE_TOKEN "
                "(preferred) or OANDA_API_TOKEN."
            )

        configured_account = (
            os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
            or os.getenv("OANDA_ACCOUNT_ID", "").strip()
        )
        if configured_account.upper() in {"YOUR_ACCOUNT_ID", "ACCOUNT_ID", "YOUR_OANDA_ACCOUNT_ID"}:
            configured_account = ""

        base = os.getenv(
            "OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com"
        ).rstrip("/")
        self.base_url = base if base.endswith("/v3") else f"{base}/v3"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.account_id = configured_account or self._discover_account_id()

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

    def _discover_account_id(self) -> str:
        payload = self._request("GET", "/accounts")
        accounts = payload.get("accounts") or []
        account_ids = [str(account.get("id")) for account in accounts if account.get("id")]
        if not account_ids:
            raise RuntimeError("OANDA practice token authenticated but no practice accounts were returned.")
        if len(account_ids) > 1:
            raise RuntimeError(
                "Multiple OANDA practice accounts were returned. Set "
                "OANDA_PRACTICE_ACCOUNT_ID to choose one explicitly."
            )
        return account_ids[0]

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
