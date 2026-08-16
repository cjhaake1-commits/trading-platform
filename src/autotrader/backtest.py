from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev


@dataclass(frozen=True)
class BacktestMetrics:
    cumulative_return_pct: float
    annualized_return_pct: float | None
    sharpe_ratio: float | None
    maximum_drawdown_pct: float
    observations: int


def compute_metrics(
    equity_curve: list[float],
    *,
    periods_per_year: int = 252,
    risk_free_period_return: float = 0.0,
) -> BacktestMetrics:
    """Compute the core evaluation metrics used by the source research.

    The function accepts an already-generated equity curve. Strategy simulation
    and market-data alignment are kept separate so this metric layer stays easy
    to verify and cannot introduce look-ahead behavior by itself.
    """

    if len(equity_curve) < 2:
        raise ValueError("Equity curve requires at least two observations")
    if any(value <= 0 for value in equity_curve):
        raise ValueError("Equity values must be positive")

    start = equity_curve[0]
    end = equity_curve[-1]
    cumulative = ((end / start) - 1.0) * 100.0

    periods = len(equity_curve) - 1
    annualized: float | None = None
    if periods > 0:
        annualized = ((end / start) ** (periods_per_year / periods) - 1.0) * 100.0

    returns = [
        (equity_curve[i] / equity_curve[i - 1]) - 1.0
        for i in range(1, len(equity_curve))
    ]
    excess = [r - risk_free_period_return for r in returns]
    volatility = pstdev(excess) if len(excess) > 1 else 0.0
    sharpe = None
    if volatility > 0:
        sharpe = (mean(excess) / volatility) * sqrt(periods_per_year)

    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = (peak - value) / peak
        max_drawdown = max(max_drawdown, drawdown)

    return BacktestMetrics(
        cumulative_return_pct=cumulative,
        annualized_return_pct=annualized,
        sharpe_ratio=sharpe,
        maximum_drawdown_pct=max_drawdown * 100.0,
        observations=len(equity_curve),
    )
