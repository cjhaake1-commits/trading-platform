from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    net_return_pct: float
    max_drawdown_pct: float
    observations: int
    slippage_bps: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RobustnessPolicy:
    min_scenarios: int = 4
    min_positive_scenario_fraction: float = 0.60
    max_worst_drawdown_pct: float = 25.0
    require_positive_average_return: bool = True


@dataclass(frozen=True)
class RobustnessAssessment:
    passed: bool
    reason: str
    average_return_pct: float
    worst_return_pct: float
    worst_drawdown_pct: float
    positive_scenario_fraction: float
    scenarios: int


class RobustnessEvaluator:
    """Reject attractive headline returns that collapse under realistic stress.

    Typical scenarios should vary fees, spread/slippage, execution latency,
    parameter choices, market regimes, and out-of-sample windows. The evaluator
    does not lower the platform's return ambition; it tests whether apparent edge
    survives conditions likely to occur outside the best historical sample.
    """

    def __init__(self, policy: RobustnessPolicy | None = None) -> None:
        self.policy = policy or RobustnessPolicy()

    def assess(self, results: list[ScenarioResult]) -> RobustnessAssessment:
        if not results:
            raise ValueError("at least one scenario result is required")

        returns = [item.net_return_pct for item in results]
        drawdowns = [item.max_drawdown_pct for item in results]
        average_return = mean(returns)
        worst_return = min(returns)
        worst_drawdown = max(drawdowns)
        positive_fraction = sum(value > 0 for value in returns) / len(returns)

        failures: list[str] = []
        if len(results) < self.policy.min_scenarios:
            failures.append("insufficient stress scenarios")
        if positive_fraction < self.policy.min_positive_scenario_fraction:
            failures.append("edge is not positive across enough scenarios")
        if worst_drawdown > self.policy.max_worst_drawdown_pct:
            failures.append("stress drawdown exceeds tolerance")
        if self.policy.require_positive_average_return and average_return <= 0:
            failures.append("average stressed return is not positive")

        return RobustnessAssessment(
            passed=not failures,
            reason="robustness checks passed" if not failures else "; ".join(failures),
            average_return_pct=average_return,
            worst_return_pct=worst_return,
            worst_drawdown_pct=worst_drawdown,
            positive_scenario_fraction=positive_fraction,
            scenarios=len(results),
        )
