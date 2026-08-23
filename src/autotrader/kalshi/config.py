from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class KalshiConfig:
    """Configuration only; no credentials are loaded unless explicitly used."""

    enabled: bool = False
    trading_enabled: bool = False
    environment: str = "demo"
    api_key_id: str | None = None
    private_key_path: str | None = None
    paper_capital: float = 0.0
    base_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    predictions_rest_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    predictions_websocket_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    perps_rest_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    perps_websocket_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    fix_url: str = "fix-demo://kalshi-disabled"

    @classmethod
    def from_env(cls) -> "KalshiConfig":
        return cls(
            enabled=_flag("KALSHI_ENABLED"),
            trading_enabled=_flag("KALSHI_TRADING_ENABLED"),
            environment=os.getenv("KALSHI_ENV", "demo").strip().lower() or "demo",
            api_key_id=os.getenv("KALSHI_API_KEY_ID") or None,
            private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH") or None,
            paper_capital=float(os.getenv("KALSHI_PAPER_CAPITAL", "0") or 0),
        )

    @property
    def research_only(self) -> bool:
        return not self.enabled and not self.trading_enabled

    def can_trade(self) -> bool:
        return False

    @property
    def broker_control(self) -> bool:
        return False
