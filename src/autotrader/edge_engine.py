"""Pure, paper-only accounting, attribution, and benchmark calculations.

The functions in this module accept normalized provider observations. They do
not call brokers, submit orders, or mutate allocation controls.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class AccountingSnapshot:
    pillar: str
    allocation_cap: float
    starting_equity: float
    available_cash: float
    deployed_cash: float
    notional_exposure: float
    pending: float
    realized_today: float
    unrealized: float
    position_market_value: float
    source: str

    @property
    def economic_equity(self) -> float:
        return self.starting_equity + self.realized_today + self.unrealized

    @property
    def total_pnl(self) -> float:
        return self.realized_today + self.unrealized

    @property
    def daily_return(self) -> float:
        return self.total_pnl / self.starting_equity if self.starting_equity else 0.0

    def verify(self, tolerance: float = 1e-6) -> dict[str, Any]:
        identity = self.economic_equity - (self.available_cash + self.position_market_value + self.pending)
        return {
            "pillar": self.pillar,
            "accounting_status": "ACCOUNTING_VERIFIED" if abs(identity) <= tolerance else "ACCOUNTING_UNVERIFIED",
            "identity_difference": identity,
            "source": self.source,
        }


def verified_outcomes(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only explicitly reconciled outcomes; missing status is unsafe."""
    return [r for r in records if str(r.get("accounting_status", "")).upper() == "ACCOUNTING_VERIFIED"]


def benchmark_metrics(outcomes: Iterable[dict[str, Any]], *, benchmark_return: float = 0.0,
                      starting_equity: float = 0.0) -> dict[str, Any]:
    rows = list(verified_outcomes(outcomes))
    returns = [float(r.get("net_realized_pnl") or r.get("realized_pnl") or 0.0) for r in rows]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    equity = starting_equity or float(sum(abs(x) for x in returns) or 1.0)
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    excess = cumulative / equity - benchmark_return
    average = mean(returns) if returns else 0.0
    variance = sum((x - average) ** 2 for x in returns) / len(returns) if returns else 0.0
    downside = sqrt(sum(min(x, 0.0) ** 2 for x in returns) / len(returns)) if returns else 0.0
    return {
        "sample_size": len(returns), "strategy_return": cumulative / equity,
        "benchmark_return": benchmark_return, "excess_return": excess,
        "expectancy": mean(returns) if returns else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0.0,
        "drawdown": drawdown / equity,
        "sharpe_like": average / sqrt(variance) if variance > 0 else 0.0,
        "sortino_like": average / downside if downside > 0 and average > 0 else 0.0,
        "return_per_dollar": cumulative / equity, "verified_only": True,
    }


def classify_edge(metrics: dict[str, Any], *, minimum_sample: int = 30) -> str:
    if metrics.get("sample_size", 0) < minimum_sample:
        return "LEARNING"
    if metrics.get("expectancy", 0.0) <= 0 or metrics.get("excess_return", 0.0) <= 0:
        return "DEVELOPING_EDGE"
    if metrics.get("drawdown", 1.0) > 0.20:
        return "DEVELOPING_EDGE"
    return "EDGE_EMERGING"


def crypto_churn_state(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(trades)
    ordered = sorted(rows, key=lambda r: str(r.get("exit_timestamp") or r.get("entry_timestamp") or ""))
    sequence_pnl = [float(r.get("net_realized_pnl") or 0.0) for r in ordered]
    repeats = Counter(str(r.get("symbol") or "UNKNOWN") for r in ordered)
    repeat_pnl = sum(
        pnl for pnl, row in zip(sequence_pnl, ordered, strict=True)
        if repeats[str(row.get("symbol") or "UNKNOWN")] > 1
    )
    holds = [float(r["holding_seconds"]) for r in ordered if r.get("holding_seconds") is not None]
    state = "NORMAL"
    if len(rows) >= 20 and (sum(1 for count in repeats.values() if count > 1) >= 3 or (holds and mean(holds) < 900)):
        state = "CHURN_DETECTED"
    elif sum(1 for x in sequence_pnl if x < 0) >= 3:
        state = "LOSS_CLUSTER"
    return {"state": state, "trades": len(rows), "sequence_pnl": sequence_pnl,
            "repeat_entries": dict(repeats), "repeat_entry_pnl": repeat_pnl,
            "average_hold_seconds": mean(holds) if holds else None}
