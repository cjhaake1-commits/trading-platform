from __future__ import annotations

from dataclasses import dataclass

from .models import PortfolioState, Position


@dataclass(frozen=True)
class PositionRisk:
    symbol: str
    quantity: float
    mark_price: float
    stop_price: float
    open_risk_dollars: float
    open_risk_pct_equity: float
    unrealized_pnl: float


@dataclass(frozen=True)
class PortfolioOpenRisk:
    total_open_risk_dollars: float
    total_open_risk_pct_equity: float
    positions: tuple[PositionRisk, ...]


def long_position_risk(
    position: Position,
    *,
    mark_price: float,
    equity: float,
) -> PositionRisk:
    if position.quantity < 0:
        raise ValueError("long_position_risk does not support short positions")
    if mark_price <= 0 or equity <= 0:
        raise ValueError("mark_price and equity must be positive")
    stop_distance = max(mark_price - position.stop_price, 0.0)
    open_risk = position.quantity * stop_distance
    unrealized = position.quantity * (mark_price - position.average_price)
    return PositionRisk(
        symbol=position.symbol,
        quantity=position.quantity,
        mark_price=mark_price,
        stop_price=position.stop_price,
        open_risk_dollars=open_risk,
        open_risk_pct_equity=open_risk / equity,
        unrealized_pnl=unrealized,
    )


def portfolio_open_risk(
    portfolio: PortfolioState,
    *,
    mark_prices: dict[str, float],
) -> PortfolioOpenRisk:
    if portfolio.equity <= 0:
        raise ValueError("portfolio equity must be positive")
    risks: list[PositionRisk] = []
    for symbol, position in portfolio.positions.items():
        mark = mark_prices.get(symbol, position.average_price)
        risks.append(long_position_risk(position, mark_price=mark, equity=portfolio.equity))
    total = sum(item.open_risk_dollars for item in risks)
    return PortfolioOpenRisk(
        total_open_risk_dollars=total,
        total_open_risk_pct_equity=total / portfolio.equity,
        positions=tuple(risks),
    )
