from __future__ import annotations

from dataclasses import dataclass

from .config import KalshiConfig


@dataclass(frozen=True)
class KalshiEndpoints:
    predictions_rest: str
    predictions_websocket: str
    perps_rest: str
    perps_websocket: str
    fix: str

    @classmethod
    def demo(cls) -> "KalshiEndpoints":
        return cls(
            "https://demo-api.kalshi.co/trade-api/v2",
            "wss://demo-api.kalshi.co/trade-api/ws/v2",
            "https://demo-api.kalshi.co/trade-api/v2", 
            "wss://demo-api.kalshi.co/trade-api/ws/v2",
            "fix-demo://kalshi-disabled",
        )


def endpoints_for(config: KalshiConfig) -> KalshiEndpoints:
    if config.environment != "demo":
        raise ValueError("only Demo endpoints are permitted")
    return KalshiEndpoints.demo()

