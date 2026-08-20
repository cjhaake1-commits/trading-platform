from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from .capital_allocations import (
    PILLAR_ALLOCATIONS,
    PILLAR_INTERNATIONAL,
    PILLAR_METALS,
    TOTAL_PAPER_CAPITAL,
)

PILLAR_LABELS = ("Stocks", "Forex", "Crypto", "Metals/Commodities", "International")
DISPLAY_ALLOCATIONS = {
    "Stocks": PILLAR_ALLOCATIONS["alpaca_equities"],
    "Forex": PILLAR_ALLOCATIONS["oanda_fx"],
    "Crypto": PILLAR_ALLOCATIONS["alpaca_crypto"],
    "Metals/Commodities": PILLAR_ALLOCATIONS[PILLAR_METALS],
    "International": PILLAR_ALLOCATIONS[PILLAR_INTERNATIONAL],
}


@dataclass(frozen=True)
class CashDashboardMetrics:
    original_capital: float
    net_trading_cash_generated: float
    available_cash: float
    protected_cash_reserve: float
    capital_deployed: float
    unrealized_pnl: float
    total_portfolio_equity: float
    generated_cash_ratio: float
    realized_pnl_by_pillar: dict[str, float]
    pillar_allocations: dict[str, float]
    broker_reported_virtual_equity: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "original_capital": self.original_capital,
            "net_trading_cash_generated": self.net_trading_cash_generated,
            "available_cash": self.available_cash,
            "protected_cash_reserve": self.protected_cash_reserve,
            "capital_deployed": self.capital_deployed,
            "unrealized_pnl": self.unrealized_pnl,
            "total_portfolio_equity": self.total_portfolio_equity,
            "generated_cash_ratio": self.generated_cash_ratio,
            "realized_pnl_by_pillar": dict(self.realized_pnl_by_pillar),
            "pillar_allocations": dict(self.pillar_allocations),
            "broker_reported_virtual_equity": self.broker_reported_virtual_equity,
        }


def aggregate_cash_dashboard(
    *,
    realized_records: Iterable[Mapping[str, object]],
    positions: Iterable[Mapping[str, object]],
    available_cash: float,
    protected_cash_reserve: float = 0.0,
    original_capital: float = TOTAL_PAPER_CAPITAL,
    broker_reported_virtual_equity: float | None = None,
) -> CashDashboardMetrics:
    realized_by_pillar = {label: 0.0 for label in PILLAR_LABELS}
    net_cash = 0.0
    for record in realized_records:
        realized = _number(record.get("realized_pnl"))
        costs = _costs(record)
        net = realized - costs
        net_cash += net
        realized_by_pillar[_pillar_label(record)] += net

    deployed = 0.0
    unrealized = 0.0
    for position in positions:
        deployed += abs(_number(position.get("market_value") or position.get("notional")))
        unrealized += _number(position.get("unrealized_pnl"))

    equity = original_capital + net_cash + unrealized
    return CashDashboardMetrics(
        original_capital=original_capital,
        net_trading_cash_generated=net_cash,
        available_cash=available_cash,
        protected_cash_reserve=protected_cash_reserve,
        capital_deployed=deployed,
        unrealized_pnl=unrealized,
        total_portfolio_equity=equity,
        generated_cash_ratio=net_cash / original_capital if original_capital else 0.0,
        realized_pnl_by_pillar=realized_by_pillar,
        pillar_allocations=dict(DISPLAY_ALLOCATIONS),
        broker_reported_virtual_equity=broker_reported_virtual_equity,
    )


def _costs(record: Mapping[str, object]) -> float:
    direct = record.get("fees_costs")
    if direct is not None:
        return _number(direct)
    metadata = record.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        return 0.0
    return sum(_number(metadata.get(key)) for key in ("fees", "commission", "costs", "trading_costs"))


def _pillar_label(record: Mapping[str, object]) -> str:
    raw = str(record.get("pillar") or "").lower()
    broker = str(record.get("broker") or "").lower()
    symbol = str(record.get("symbol") or record.get("instrument") or "").upper()
    metadata = record.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if isinstance(metadata, dict):
        raw = str(metadata.get("pillar") or raw).lower()
    if raw in {PILLAR_INTERNATIONAL, "international"} or "saxo" in broker:
        return "International"
    if raw == PILLAR_METALS or "metal" in raw or "commod" in raw or symbol.startswith(("XAU", "XAG")):
        return "Metals/Commodities"
    if "forex" in raw or "oanda" in broker:
        return "Forex"
    if "crypto" in raw or "crypto" in broker:
        return "Crypto"
    return "Stocks"


def _number(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
