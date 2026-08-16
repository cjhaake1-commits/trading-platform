from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeIntent(StrEnum):
    """Describe the intended position lifecycle separately from order direction."""

    ENTER = "enter"
    INCREASE = "increase"
    REDUCE = "reduce"
    EXIT = "exit"


class AssetClass(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    FOREX = "forex"
    FUTURE = "future"
    OPTION = "option"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    asset_class: AssetClass
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("High price must be greater than or equal to OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Low price must be less than or equal to OHLC values")
        if self.volume < 0:
            raise ValueError("Volume cannot be negative")


@dataclass(frozen=True)
class ScanCandidate:
    instrument: Instrument
    score: float
    last_price: float
    momentum_pct: float
    average_range_pct: float
    volume_ratio: float | None
    suggested_stop: float
    reasons: tuple[str, ...] = ()


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
    intent: TradeIntent = TradeIntent.ENTER
    requested_quantity: float | None = None

    def __post_init__(self) -> None:
        if self.requested_quantity is not None and self.requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive when supplied")

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
    realized_pnl: float = 0.0
    initial_stop_price: float | None = None
    highest_price: float | None = None
    opened_at: datetime | None = None


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
    risk_scale: float = 1.0
    binding_constraint: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    message: str
    data: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
