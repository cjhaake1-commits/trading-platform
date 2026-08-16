from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class EdgeForecast:
    """Pre-trade estimate used to rank opportunities, never to bypass risk controls."""

    symbol: str
    strategy_id: str
    win_probability: float
    average_win_bps: float
    average_loss_bps: float
    explicit_cost_bps: float = 0.0
    spread_bps: float = 0.0
    expected_slippage_bps: float = 0.0
    signal_half_life_ms: float | None = None
    estimated_execution_latency_ms: float = 0.0
    confidence: float = 1.0
    capacity_notional: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.win_probability <= 1.0:
            raise ValueError("win_probability must be between 0 and 1")
        if self.average_win_bps < 0 or self.average_loss_bps < 0:
            raise ValueError("average win/loss magnitudes cannot be negative")
        if min(self.explicit_cost_bps, self.spread_bps, self.expected_slippage_bps) < 0:
            raise ValueError("cost estimates cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.signal_half_life_ms is not None and self.signal_half_life_ms <= 0:
            raise ValueError("signal_half_life_ms must be positive")
        if self.estimated_execution_latency_ms < 0:
            raise ValueError("estimated_execution_latency_ms cannot be negative")
        if self.capacity_notional is not None and self.capacity_notional <= 0:
            raise ValueError("capacity_notional must be positive")

    @property
    def gross_expectancy_bps(self) -> float:
        loss_probability = 1.0 - self.win_probability
        return (
            self.win_probability * self.average_win_bps
            - loss_probability * self.average_loss_bps
        )

    @property
    def total_cost_bps(self) -> float:
        return self.explicit_cost_bps + self.spread_bps + self.expected_slippage_bps

    @property
    def net_expectancy_bps(self) -> float:
        return self.gross_expectancy_bps - self.total_cost_bps

    @property
    def latency_survival(self) -> float:
        """Approximate fraction of edge expected to remain by order arrival.

        Exponential decay is a deliberately simple research approximation. It is
        fitted/validated per strategy from observed edge-decay experiments.
        """

        if self.signal_half_life_ms is None or self.estimated_execution_latency_ms <= 0:
            return 1.0
        return exp(
            -0.6931471805599453
            * self.estimated_execution_latency_ms
            / self.signal_half_life_ms
        )

    @property
    def latency_adjusted_net_edge_bps(self) -> float:
        gross_after_latency = self.gross_expectancy_bps * self.latency_survival
        return gross_after_latency - self.total_cost_bps


@dataclass(frozen=True)
class EdgeAllocationPolicy:
    min_net_edge_bps: float = 1.0
    min_latency_survival: float = 0.20
    kelly_scale: float = 0.50
    max_growth_fraction: float = 0.08
    min_confidence: float = 0.50


@dataclass(frozen=True)
class RankedOpportunity:
    forecast: EdgeForecast
    eligible: bool
    reason: str
    growth_fraction: float
    priority_score: float


class EdgeOptimizer:
    """Rank opportunities by expected growth after latency and trading costs.

    The suggested growth fraction is research/paper-sizing input only. Final
    quantity remains bounded by the deterministic portfolio risk stack.
    """

    def __init__(self, policy: EdgeAllocationPolicy | None = None) -> None:
        self.policy = policy or EdgeAllocationPolicy()

    def evaluate(self, forecast: EdgeForecast) -> RankedOpportunity:
        edge = forecast.latency_adjusted_net_edge_bps
        if forecast.confidence < self.policy.min_confidence:
            return RankedOpportunity(forecast, False, "confidence below threshold", 0.0, 0.0)
        if forecast.latency_survival < self.policy.min_latency_survival:
            return RankedOpportunity(forecast, False, "edge decays before expected execution", 0.0, 0.0)
        if edge < self.policy.min_net_edge_bps:
            return RankedOpportunity(forecast, False, "net edge below threshold", 0.0, 0.0)

        growth_fraction = self._bounded_kelly_fraction(forecast)
        # Prioritize edge that survives execution and is supported by confidence.
        priority = edge * forecast.confidence * max(growth_fraction, 1e-9)
        return RankedOpportunity(
            forecast,
            True,
            "positive latency-adjusted edge",
            growth_fraction,
            priority,
        )

    def rank(self, forecasts: list[EdgeForecast]) -> list[RankedOpportunity]:
        ranked = [self.evaluate(item) for item in forecasts]
        return sorted(ranked, key=lambda item: item.priority_score, reverse=True)

    def _bounded_kelly_fraction(self, forecast: EdgeForecast) -> float:
        if forecast.average_loss_bps <= 0:
            return 0.0
        payoff_ratio = forecast.average_win_bps / forecast.average_loss_bps
        if payoff_ratio <= 0:
            return 0.0
        p = forecast.win_probability
        q = 1.0 - p
        full_kelly = p - (q / payoff_ratio)
        if full_kelly <= 0:
            return 0.0
        scaled = full_kelly * self.policy.kelly_scale * forecast.confidence
        return min(max(scaled, 0.0), self.policy.max_growth_fraction)
