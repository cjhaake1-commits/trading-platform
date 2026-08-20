from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from .capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL

FIVE_PILLAR_BASELINE_VERSION = "five_pillar_baseline_v1"
PILLAR_NAMES = {
    "alpaca_equities": "US Stocks/ETFs",
    "oanda_fx": "Forex",
    "alpaca_crypto": "Crypto",
    "alpaca_metals": "Metals/Commodities",
    "ibkr_global": "International",
}
IMMUTABLE_SAFETY_CONTROLS = (
    "broker_environment_locks",
    "pillar_allocations",
    "portfolio_risk",
    "risk_per_trade",
    "drawdown_shutdowns",
    "cash_reserve",
    "emergency_kill_switches",
)


@dataclass(frozen=True)
class FivePillarTestConfig:
    baseline_version: str = FIVE_PILLAR_BASELINE_VERSION

    @property
    def allocations(self) -> dict[str, float]:
        return {PILLAR_NAMES[key]: value for key, value in PILLAR_ALLOCATIONS.items()}

    @property
    def total_starting_capital(self) -> float:
        return TOTAL_PAPER_CAPITAL

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline_version": self.baseline_version,
            "allocations": self.allocations,
            "total_starting_capital": self.total_starting_capital,
            "broker_excess_balance_deployable": False,
            "immutable_safety_controls": list(IMMUTABLE_SAFETY_CONTROLS),
        }


def five_pillar_performance(
    *,
    completed_trades: Iterable[Mapping[str, object]],
    positions: Iterable[Mapping[str, object]],
    protected_cash: Mapping[str, float] | None = None,
) -> dict[str, dict[str, float | int | None]]:
    protected = protected_cash or {}
    trades_by_pillar = {name: [] for name in PILLAR_NAMES.values()}
    positions_by_pillar = {name: [] for name in PILLAR_NAMES.values()}
    for trade in completed_trades:
        trades_by_pillar[_pillar_name(trade)].append(trade)
    for position in positions:
        positions_by_pillar[_pillar_name(position)].append(position)

    output = {}
    for name in PILLAR_NAMES.values():
        allocation = 1000.0
        rows = trades_by_pillar[name]
        gross = [_number(row.get("realized_pnl")) for row in rows]
        costs = [_costs(row) for row in rows]
        net = [pnl - cost for pnl, cost in zip(gross, costs, strict=True)]
        wins = [value for value in net if value > 0]
        losses = [value for value in net if value < 0]
        deployed = sum(
            abs(_number(row.get("market_value") or row.get("notional"))) for row in positions_by_pillar[name]
        )
        unrealized = sum(_number(row.get("unrealized_pnl")) for row in positions_by_pillar[name])
        generated = sum(net)
        reserve = _number(protected.get(name))
        current_allocation = allocation + generated
        max_drawdown, current_drawdown = _drawdowns(allocation, net)
        output[name] = {
            "starting_allocation": allocation,
            "current_allocation": current_allocation,
            "capital_deployed": deployed,
            "available_cash": max(current_allocation - deployed - reserve, 0.0),
            "protected_cash": reserve,
            "realized_gross_profit": sum(value for value in gross if value > 0),
            "realized_losses": abs(sum(value for value in gross if value < 0)),
            "trading_costs": sum(costs),
            "net_generated_cash": generated,
            "unrealized_pnl": unrealized,
            "total_equity": current_allocation + unrealized,
            "number_of_trades": len(net),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(net) if net else 0.0,
            "average_win": sum(wins) / len(wins) if wins else 0.0,
            "average_loss": sum(losses) / len(losses) if losses else 0.0,
            "expectancy": sum(net) / len(net) if net else 0.0,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else (None if wins else 0.0),
            "maximum_drawdown": max_drawdown,
            "current_drawdown": current_drawdown,
        }
    return output


def _drawdowns(starting: float, outcomes: list[float]) -> tuple[float, float]:
    equity = peak = starting
    maximum = 0.0
    for outcome in outcomes:
        equity += outcome
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak if peak else 0.0)
    return maximum, (peak - equity) / peak if peak else 0.0


def _pillar_name(row: Mapping[str, object]) -> str:
    raw = str(row.get("pillar") or "").lower()
    broker = str(row.get("broker") or "").lower()
    symbol = str(row.get("symbol") or row.get("instrument") or "").upper()
    metadata = row.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if isinstance(metadata, dict):
        raw = str(metadata.get("pillar") or raw).lower()
    if "saxo" in broker or raw in {"international", "ibkr_global"}:
        return "International"
    if "metal" in raw or symbol in {"GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL"}:
        return "Metals/Commodities"
    if "oanda" in broker or "forex" in raw:
        return "Forex"
    if "crypto" in broker or "crypto" in raw:
        return "Crypto"
    return "US Stocks/ETFs"


def _costs(row: Mapping[str, object]) -> float:
    if row.get("fees_costs") is not None:
        return _number(row.get("fees_costs"))
    metadata = row.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    return (
        sum(_number(metadata.get(key)) for key in ("fees", "commission", "costs"))
        if isinstance(metadata, dict)
        else 0.0
    )


def _number(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
