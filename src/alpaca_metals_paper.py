from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import requests
from dotenv import load_dotenv

load_dotenv()

METALS_UNIVERSE = ("GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL")


@dataclass(frozen=True)
class MetalsRiskLimits:
    pillar_capital: Decimal = Decimal("1000")
    risk_per_trade: Decimal = Decimal("0.005")
    minimum_cash_reserve: Decimal = Decimal("0.25")
    max_metals_exposure: Decimal = Decimal("0.20")
    max_single_position: Decimal = Decimal("0.075")


class AlpacaMetalsPaperClient:
    """Paper-only Alpaca adapter for exchange-traded metals exposure."""

    def __init__(self) -> None:
        env = os.getenv("ALPACA_ENV", "paper").lower()
        if env != "paper":
            raise RuntimeError("Safety lock: only Alpaca paper trading is allowed.")

        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_API_SECRET"]
        self.trading_url = "https://paper-api.alpaca.markets/v2"
        self.data_url = "https://data.alpaca.markets/v2"
        self.headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
        }

    def _request(self, method: str, url: str, **kwargs):
        response = requests.request(method, url, headers=self.headers, timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()

    def account(self):
        return self._request("GET", f"{self.trading_url}/account")

    def asset(self, symbol: str):
        return self._request("GET", f"{self.trading_url}/assets/{symbol.upper()}")

    def tradable_metals(self) -> list[str]:
        tradable: list[str] = []
        for symbol in METALS_UNIVERSE:
            try:
                asset = self.asset(symbol)
            except requests.HTTPError:
                continue
            if asset.get("status") == "active" and asset.get("tradable") is True:
                tradable.append(symbol)
        return tradable

    def latest_trade(self, symbol: str):
        return self._request("GET", f"{self.data_url}/stocks/{symbol.upper()}/trades/latest")

    def bracket_order(
        self,
        symbol: str,
        qty: int,
        stop_loss_price: str,
        take_profit_price: str,
    ):
        if qty < 1:
            raise ValueError("Quantity must be at least one share.")
        if not stop_loss_price or not take_profit_price:
            raise ValueError("Every paper entry requires stop-loss and take-profit prices.")
        if symbol.upper() not in METALS_UNIVERSE:
            raise ValueError("Symbol is outside the approved metals universe.")

        payload = {
            "symbol": symbol.upper(),
            "qty": str(qty),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(take_profit_price)},
            "stop_loss": {"stop_price": str(stop_loss_price)},
        }
        return self._request("POST", f"{self.trading_url}/orders", json=payload)


def position_shares(
    account_equity: Decimal,
    available_cash: Decimal,
    entry: Decimal,
    stop: Decimal,
    current_metals_exposure: Decimal,
    limits: MetalsRiskLimits = MetalsRiskLimits(),
) -> int:
    """Size a long paper position subject to risk, cash reserve, and exposure caps."""
    if min(account_equity, available_cash, entry) <= 0:
        raise ValueError("Equity, cash, and entry price must be positive.")
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("Stop must differ from entry price.")

    pillar_equity = min(account_equity, limits.pillar_capital)
    risk_budget = pillar_equity * limits.risk_per_trade
    by_stop = risk_budget / distance

    reserve_floor = account_equity * limits.minimum_cash_reserve
    deployable_cash = max(Decimal("0"), available_cash - reserve_floor)
    by_cash = deployable_cash / entry

    single_cap = pillar_equity * limits.max_single_position
    by_single = single_cap / entry

    metals_cap = pillar_equity * limits.max_metals_exposure
    remaining_metals = max(Decimal("0"), metals_cap - current_metals_exposure)
    by_metals = remaining_metals / entry

    shares = min(by_stop, by_cash, by_single, by_metals).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return max(0, int(shares))
