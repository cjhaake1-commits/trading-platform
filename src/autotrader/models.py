from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    FOREX = "forex"
    FUTURE = "future"
    OPTION = "option"


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    asset_class: AssetClass
    side: Side
    entry_price: float
    stop_price: float
    confidence: float
    source: str
    rationale: str = ""

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_price)


@dataclass
class Position:
    symbol: str
    asset_class: AssetClass
    quantity: float
    average_price: float
    stop_price: float


@dataclass
class PortfolioState:
    equity: float
    cash: float
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    quantity: float = 0.0
    max_loss_dollars: float = 0.0


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    message: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
