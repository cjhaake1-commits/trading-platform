from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyReturnTargets:
    milestone_10_pct: float = 0.10
    stretch_20_pct: float = 0.20
    stretch_30_pct: float = 0.30


@dataclass(frozen=True)
class DailyPerformanceSnapshot:
    start_equity: float
    current_equity: float
    realized_pnl: float
    unrealized_pnl: float = 0.0

    @property
    def return_pct(self) -> float:
        if self.start_equity <= 0:
            raise ValueError("start_equity must be positive")
        return (self.current_equity / self.start_equity) - 1.0


class StretchGoalTracker:
    """Report progress toward ambitious daily return thresholds.

    This tracker is intentionally observational. It never increases leverage,
    trade frequency, or position size simply because a return threshold has not
    been reached.
    """

    def __init__(self, targets: DailyReturnTargets | None = None) -> None:
        self.targets = targets or DailyReturnTargets()

    def status(self, snapshot: DailyPerformanceSnapshot) -> dict[str, object]:
        daily_return = snapshot.return_pct
        return {
            "daily_return_pct": daily_return * 100.0,
            "hit_10_pct": daily_return >= self.targets.milestone_10_pct,
            "hit_20_pct": daily_return >= self.targets.stretch_20_pct,
            "hit_30_pct": daily_return >= self.targets.stretch_30_pct,
            "distance_to_20_pct_points": max(
                (self.targets.stretch_20_pct - daily_return) * 100.0,
                0.0,
            ),
            "distance_to_30_pct_points": max(
                (self.targets.stretch_30_pct - daily_return) * 100.0,
                0.0,
            ),
            "realized_pnl": snapshot.realized_pnl,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "quota_driven_sizing_allowed": False,
        }
