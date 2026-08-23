from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CalibrationPoint:
    probability: float
    outcome: int
    category: str = "unknown"
    horizon: str = "unknown"


@dataclass(frozen=True)
class CalibrationSummary:
    samples: int
    brier_score: float | None
    mean_probability: float | None
    realized_frequency: float | None
    calibration_gap: float | None


@dataclass(frozen=True)
class LeadLagPoint:
    kalshi_change: float
    asset_return: float
    lag_seconds: int
    pillar: str
    symbol: str
    regime: str = "unknown"


@dataclass(frozen=True)
class LeadLagSummary:
    samples: int
    correlation: float | None
    directional_hit_rate: float | None
    mean_asset_return_when_kalshi_up: float | None
    mean_asset_return_when_kalshi_down: float | None


@dataclass(frozen=True)
class CrossMarketLearningNode:
    source_feature: str
    pillar: str
    symbol: str
    regime: str
    sample_size: int
    correlation: float | None
    directional_hit_rate: float | None
    calibration_brier: float | None
    evidence_state: str
    research_weight: float = 0.0
    broker_control: bool = False


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def calibration_summary(points: Iterable[CalibrationPoint]) -> CalibrationSummary:
    valid = [p for p in points if 0.0 <= p.probability <= 1.0 and p.outcome in {0, 1}]
    if not valid:
        return CalibrationSummary(0, None, None, None, None)
    probs = [p.probability for p in valid]
    outcomes = [float(p.outcome) for p in valid]
    brier = mean((p - y) ** 2 for p, y in zip(probs, outcomes, strict=True))
    avg_probability = mean(probs)
    frequency = mean(outcomes)
    return CalibrationSummary(
        samples=len(valid),
        brier_score=brier,
        mean_probability=avg_probability,
        realized_frequency=frequency,
        calibration_gap=frequency - avg_probability,
    )


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denom == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy, strict=True)) / denom


def lead_lag_summary(points: Iterable[LeadLagPoint]) -> LeadLagSummary:
    valid = [p for p in points if _finite(p.kalshi_change) is not None and _finite(p.asset_return) is not None]
    if not valid:
        return LeadLagSummary(0, None, None, None, None)
    x = [p.kalshi_change for p in valid]
    y = [p.asset_return for p in valid]
    nonzero = [p for p in valid if p.kalshi_change != 0 and p.asset_return != 0]
    hit_rate = None
    if nonzero:
        hits = sum(1 for p in nonzero if (p.kalshi_change > 0) == (p.asset_return > 0))
        hit_rate = hits / len(nonzero)
    up = [p.asset_return for p in valid if p.kalshi_change > 0]
    down = [p.asset_return for p in valid if p.kalshi_change < 0]
    return LeadLagSummary(
        samples=len(valid),
        correlation=_correlation(x, y),
        directional_hit_rate=hit_rate,
        mean_asset_return_when_kalshi_up=mean(up) if up else None,
        mean_asset_return_when_kalshi_down=mean(down) if down else None,
    )


def evidence_state(
    *,
    samples: int,
    correlation: float | None,
    directional_hit_rate: float | None,
    calibration_brier: float | None,
    minimum_samples: int = 30,
) -> str:
    if samples < minimum_samples:
        return "COLLECTING_EVIDENCE"
    if correlation is None and directional_hit_rate is None:
        return "INSUFFICIENT_SIGNAL"
    predictive = (abs(correlation or 0.0) >= 0.20) or ((directional_hit_rate or 0.0) >= 0.58)
    calibrated = calibration_brier is None or calibration_brier <= 0.25
    return "SHADOW_CANDIDATE" if predictive and calibrated else "RESEARCH_ONLY"


def build_learning_node(
    *,
    source_feature: str,
    pillar: str,
    symbol: str,
    regime: str,
    lead_lag: LeadLagSummary,
    calibration: CalibrationSummary | None = None,
    minimum_samples: int = 30,
) -> CrossMarketLearningNode:
    if not source_feature.startswith("kalshi."):
        raise ValueError("source_feature must be namespaced under kalshi.*")
    brier = calibration.brier_score if calibration is not None else None
    state = evidence_state(
        samples=lead_lag.samples,
        correlation=lead_lag.correlation,
        directional_hit_rate=lead_lag.directional_hit_rate,
        calibration_brier=brier,
        minimum_samples=minimum_samples,
    )
    return CrossMarketLearningNode(
        source_feature=source_feature,
        pillar=pillar,
        symbol=symbol,
        regime=regime,
        sample_size=lead_lag.samples,
        correlation=lead_lag.correlation,
        directional_hit_rate=lead_lag.directional_hit_rate,
        calibration_brier=brier,
        evidence_state=state,
        research_weight=0.0,
        broker_control=False,
    )


def cross_pillar_targets(category: str) -> tuple[str, ...]:
    key = category.strip().lower()
    mapping: Mapping[str, tuple[str, ...]] = {
        "fed": ("Stocks", "Forex", "Metals/Commodities", "International", "Crypto"),
        "rates": ("Stocks", "Forex", "Metals/Commodities", "International", "Crypto"),
        "inflation": ("Stocks", "Forex", "Metals/Commodities", "International", "Crypto"),
        "employment": ("Stocks", "Forex", "Metals/Commodities", "International"),
        "crypto": ("Crypto", "Stocks"),
        "bitcoin": ("Crypto", "Stocks"),
        "energy": ("Metals/Commodities", "Stocks", "Forex", "International"),
        "oil": ("Metals/Commodities", "Stocks", "Forex", "International"),
        "weather": ("Metals/Commodities", "Stocks"),
        "elections": ("Stocks", "Forex", "International", "Crypto"),
        "policy": ("Stocks", "Forex", "International", "Crypto", "Metals/Commodities"),
    }
    return mapping.get(key, ("Stocks", "Crypto", "Forex", "Metals/Commodities", "International"))


def candidate_feature_weight(node: CrossMarketLearningNode) -> float:
    """Return a shadow-only candidate weight; never grants execution control.

    The active five-pillar learner must not consume this value until a separate
    challenger promotion process explicitly validates and enables it.
    """
    if node.evidence_state != "SHADOW_CANDIDATE":
        return 0.0
    corr_strength = min(abs(node.correlation or 0.0), 1.0)
    hit_strength = max((node.directional_hit_rate or 0.5) - 0.5, 0.0) * 2.0
    return min(0.25, 0.125 * corr_strength + 0.125 * hit_strength)
