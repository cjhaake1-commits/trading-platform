"""Transparent multi-strategy evaluation and single-opportunity aggregation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean, pvariance

from .models import Instrument, MarketBar
from .strategies import BaselineStrategies

STRATEGY_METHODS = {
    "MOMENTUM": "momentum",
    "BREAKOUT": "breakout",
    "MEAN_REVERSION": "mean_reversion",
    "TREND_FOLLOWING": "trend_following",
    "RELATIVE_STRENGTH": None,
}


@dataclass(frozen=True)
class StrategyEvaluation:
    strategy_id: str
    market: str
    timeframe: str
    direction: str
    raw_score: float
    confidence: float
    estimated_edge: float | None
    expected_value: float | None
    features: dict[str, object]
    candidate: bool
    signal: bool
    rejection_reason: str | None = None
    edge_proxy: float | None = None
    ev_proxy: float | None = None
    data_quality: str = "UNKNOWN"
    regime: str = "UNKNOWN"
    strategy_version: str = "v1"


@dataclass(frozen=True)
class ConfluenceDecision:
    market: str
    direction: str
    long_votes: int
    short_votes: int
    hold_votes: int
    insufficient_data_count: int
    agreement_ratio: float
    weighted_confidence: float
    dispersion: float
    aggregate_edge_proxy: float | None
    expected_value: float | None
    strategy_votes: tuple[dict[str, object], ...]
    conflict_state: str = "NONE"


def evaluate_strategies(
    instrument: Instrument,
    bars: list[MarketBar],
    candidate_score: float,
    *,
    timeframe: str = "15m",
    strategies: BaselineStrategies | None = None,
) -> tuple[StrategyEvaluation, ...]:
    engine = strategies or BaselineStrategies()
    closes = [float(bar.close) for bar in bars if float(bar.close) > 0]
    regime = "UNKNOWN"
    if len(closes) >= 5:
        returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
        avg_abs_return = mean(abs(value) for value in returns)
        direction = closes[-1] / closes[0] - 1.0
        regime = "HIGH_VOL" if avg_abs_return >= 0.02 else ("TRENDING" if abs(direction) >= 0.03 else "RANGE")
    results: list[StrategyEvaluation] = []
    for strategy_id, method_name in STRATEGY_METHODS.items():
        proposal = getattr(engine, method_name)(instrument, bars) if method_name else None
        direction = proposal.side.value.upper() if proposal else "HOLD"
        signal = proposal is not None
        confidence = proposal.confidence if proposal else 0.0
        # Candidate score is a research ranking proxy, not calibrated
        # economics. Keep validated fields unknown until outcome calibration.
        edge_proxy = max(candidate_score / 100.0, 0.0) if signal else 0.0
        results.append(
            StrategyEvaluation(
                strategy_id=f"{instrument.asset_class.value.lower()}.{strategy_id.lower()}",
                market=instrument.symbol,
                timeframe=timeframe,
                direction=direction,
                raw_score=float(candidate_score),
                confidence=float(confidence),
                estimated_edge=None,
                expected_value=None,
                features={"bar_count": len(bars), "source_method": method_name or "INSUFFICIENT_DATA"},
                candidate=True,
                signal=signal,
                rejection_reason=None if signal else ("INSUFFICIENT_DATA" if strategy_id == "RELATIVE_STRENGTH" else "NO_STRATEGY_SIGNAL"),
                edge_proxy=edge_proxy,
                ev_proxy=edge_proxy * confidence,
                data_quality="INSUFFICIENT_DATA" if strategy_id == "RELATIVE_STRENGTH" else ("FRESH" if bars else "INSUFFICIENT_DATA"),
                regime=regime,
                strategy_version="v1",
            )
        )
    return tuple(results)


def aggregate_confluence(evaluations: tuple[StrategyEvaluation, ...]) -> ConfluenceDecision:
    if not evaluations:
        raise ValueError("at least one strategy evaluation is required")
    votes = Counter(item.direction for item in evaluations)
    directional = [item for item in evaluations if item.direction in {"BUY", "SELL"}]
    insufficient_data_count = sum(item.data_quality == "INSUFFICIENT_DATA" for item in evaluations)
    edge_proxies = [item.edge_proxy for item in evaluations if item.edge_proxy is not None]
    direction = "HOLD"
    conflict_state = "NONE"
    if directional:
        buy_confidence = mean([item.confidence for item in directional if item.direction == "BUY"] or [0.0])
        sell_confidence = mean([item.confidence for item in directional if item.direction == "SELL"] or [0.0])
        if votes["BUY"] == votes["SELL"] and abs(buy_confidence - sell_confidence) <= 0.10:
            direction = "CONFLICT"
            conflict_state = "TIED_COMPARABLE_CONFIDENCE"
        else:
            direction = "BUY" if (votes["BUY"], buy_confidence) > (votes["SELL"], sell_confidence) else "SELL"
    weights = [item.confidence for item in evaluations]
    weighted = sum(item.confidence * (1 if item.direction == direction else 0) for item in evaluations) / max(sum(weights), 1e-12)
    return ConfluenceDecision(
        market=evaluations[0].market,
        direction=direction,
        long_votes=votes["BUY"],
        short_votes=votes["SELL"],
        hold_votes=votes["HOLD"],
        insufficient_data_count=insufficient_data_count,
        agreement_ratio=(max(votes["BUY"], votes["SELL"]) / len(evaluations)) if direction == "CONFLICT" else (votes[direction] / len(evaluations) if direction != "HOLD" else votes["HOLD"] / len(evaluations)),
        weighted_confidence=0.0 if direction == "CONFLICT" else weighted,
        dispersion=pvariance(weights) if len(weights) > 1 else 0.0,
        aggregate_edge_proxy=(sum(edge_proxies) / len(edge_proxies)) if edge_proxies else None,
        expected_value=None,
        strategy_votes=tuple({"strategy_id": item.strategy_id, "direction": item.direction, "confidence": item.confidence, "regime": item.regime} for item in evaluations),
        conflict_state=conflict_state,
    )


def evaluate_proposals(
    instrument: Instrument,
    bars: list[MarketBar],
    proposals: dict[str, object | None],
    *,
    timeframe: str = "15m",
    candidate_score: float | None = None,
) -> tuple[StrategyEvaluation, ...]:
    """Normalize asset-specific proposals into the shared confluence contract.

    A missing proposal is a HOLD/NO_STRATEGY_SIGNAL observation, never a vote
    for the first available strategy.  Callers may use this for asset classes
    whose strategy calculations live outside :class:`BaselineStrategies`.
    """
    results = []
    for strategy_id, proposal in proposals.items():
        if proposal is None:
            direction, confidence, rationale = "HOLD", 0.0, "no strategy proposal"
            unavailable = strategy_id.upper() in {"RELATIVE_STRENGTH", "RELATIVE_STRENGTH_ROTATION"}
            rejection = "INSUFFICIENT_DATA" if unavailable else "NO_STRATEGY_SIGNAL"
        else:
            direction = proposal.side.value.upper()
            confidence = float(proposal.confidence)
            rationale = proposal.rationale
            rejection = None
        proxy = max(float(candidate_score or 0.0) / 100.0, 0.0) if proposal is not None else 0.0
        results.append(StrategyEvaluation(
            strategy_id=f"{instrument.asset_class.value.lower()}.{strategy_id.lower()}",
            market=instrument.symbol, timeframe=timeframe, direction=direction,
            raw_score=float(candidate_score or 0.0), confidence=confidence,
            estimated_edge=None, expected_value=None,
            features={"bar_count": len(bars), "rationale": rationale},
            candidate=True, signal=proposal is not None, rejection_reason=rejection,
            edge_proxy=proxy, ev_proxy=proxy * confidence,
            data_quality="INSUFFICIENT_DATA" if proposal is None and rejection == "INSUFFICIENT_DATA" else ("FRESH" if bars else "INSUFFICIENT_DATA"),
            regime="UNKNOWN",
            strategy_version="v1",
        ))
    return tuple(results)


__all__ = ["ConfluenceDecision", "StrategyEvaluation", "aggregate_confluence", "evaluate_proposals", "evaluate_strategies"]
