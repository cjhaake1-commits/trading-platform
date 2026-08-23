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
    base_url: str = "https://external-api.demo.kalshi.co/trade-api/v2"
    predictions_rest_url: str = "https://external-api.demo.kalshi.co/trade-api/v2"
    predictions_websocket_url: str = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
    perps_rest_url: str = "https://external-api.demo.kalshi.co/trade-api/v2/margin/"
    perps_websocket_url: str = "wss://external-api-margin-ws.demo.kalshi.co/trade-api/ws/v2/margin"
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
            perps_rest_url=os.getenv("KALSHI_PERPS_REST_URL") or cls().perps_rest_url,
            perps_websocket_url=os.getenv("KALSHI_PERPS_WEBSOCKET_URL") or cls().perps_websocket_url,
        )

    @property
    def research_only(self) -> bool:
        return not self.enabled and not self.trading_enabled

    def can_trade(self) -> bool:
        return False

    @property
    def broker_control(self) -> bool:
        return False

    @property
    def research_enabled(self) -> bool:
        return _flag("KALSHI_RESEARCH_ENABLED")

    @property
    def demo_trading_enabled(self) -> bool:
        return _flag("KALSHI_DEMO_TRADING_ENABLED") and self.environment == "demo" and not _flag("KALSHI_LIVE_TRADING_ENABLED") and not _flag("LIVE_TRADING_ENABLED")
