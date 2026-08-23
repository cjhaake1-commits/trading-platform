from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Subscription:
    family: str
    channels: tuple[str, ...]
    market_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebSocketMessage:
    family: str
    channel: str
    payload: dict[str, Any]
    sequence: int | None = None
    received_at: Any = None


@dataclass(frozen=True)
class ReconnectPolicy:
    max_attempts: int = 3
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0)

