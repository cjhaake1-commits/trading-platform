"""Transparent multi-strategy evaluation and single-opportunity aggregation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean, pvariance

from .models import Instrument, MarketBar
from .strategies import BaselineStrategies

STRATEGY_METHODS = {
    "MOMENTUM": "sma_cross",
    "BREAKOUT": "breakout",
    "MEAN_REVERSION": "mean_reversion",
    "TREND_FOLLOWING": "sma_cross",
    "RELATIVE_STRENGTH": "sma_cross",
}


@dataclass(frozen=True)
class StrategyEvaluation:
    strategy_id: str
    market: str
    timeframe: str
    direction: str
    raw_score: float
    confidence: float
    estimated_edge: float
    expected_value: float
    features: dict[str, object]
    candidate: bool
    signal: bool
    rejection_reason: str | None = None


@dataclass(frozen=True)
class ConfluenceDecision:
    market: str
    direction: str
    long_votes: int
    short_votes: int
    hold_votes: int
    agreement_ratio: float
    weighted_confidence: float
    dispersion: float
    expected_value: float
    strategy_votes: tuple[dict[str, object], ...]


def evaluate_strategies(
    instrument: Instrument,
    bars: list[MarketBar],
    candidate_score: float,
    *,
    timeframe: str = "15m",
    strategies: BaselineStrategies | None = None,
) -> tuple[StrategyEvaluation, ...]:
    engine = strategies or BaselineStrategies()
    results: list[StrategyEvaluation] = []
    for strategy_id, method_name in STRATEGY_METHODS.items():
        proposal = getattr(engine, method_name)(instrument, bars)
        direction = proposal.side.value.upper() if proposal else "HOLD"
        signal = proposal is not None
        confidence = proposal.confidence if proposal else 0.0
        edge = max(candidate_score / 100.0, 0.0) if signal else 0.0
        results.append(
            StrategyEvaluation(
                strategy_id=f"{instrument.asset_class.value.lower()}.{strategy_id.lower()}",
                market=instrument.symbol,
                timeframe=timeframe,
                direction=direction,
                raw_score=float(candidate_score),
                confidence=float(confidence),
                estimated_edge=edge,
                expected_value=edge * confidence,
                features={"bar_count": len(bars), "source_method": method_name},
                candidate=True,
                signal=signal,
                rejection_reason=None if signal else "NO_STRATEGY_SIGNAL",
            )
        )
    return tuple(results)


def aggregate_confluence(evaluations: tuple[StrategyEvaluation, ...]) -> ConfluenceDecision:
    if not evaluations:
        raise ValueError("at least one strategy evaluation is required")
    votes = Counter(item.direction for item in evaluations)
    directional = [item for item in evaluations if item.direction in {"BUY", "SELL"}]
    direction = "HOLD"
    if directional:
        direction = max(
            ("BUY", "SELL"),
            key=lambda side: (
                votes[side],
                mean([item.confidence for item in directional if item.direction == side] or [0.0]),
            ),
        )
    weights = [item.confidence for item in evaluations]
    weighted = sum(item.confidence * (1 if item.direction == direction else 0) for item in evaluations) / max(sum(weights), 1e-12)
    return ConfluenceDecision(
        market=evaluations[0].market,
        direction=direction,
        long_votes=votes["BUY"],
        short_votes=votes["SELL"],
        hold_votes=votes["HOLD"],
        agreement_ratio=votes[direction] / len(evaluations) if direction != "HOLD" else votes["HOLD"] / len(evaluations),
        weighted_confidence=weighted,
        dispersion=pvariance(weights) if len(weights) > 1 else 0.0,
        expected_value=mean(item.expected_value for item in evaluations),
        strategy_votes=tuple({"strategy_id": item.strategy_id, "direction": item.direction, "confidence": item.confidence} for item in evaluations),
    )


__all__ = ["ConfluenceDecision", "StrategyEvaluation", "aggregate_confluence", "evaluate_strategies"]
