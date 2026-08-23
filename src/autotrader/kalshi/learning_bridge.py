from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Protocol


class FeatureSink(Protocol):
    def put_feature(
        self,
        *,
        name: str,
        value: float,
        source: str,
        experiment_id: str,
        symbol: str,
        pillar: str,
        freshness: str = "FRESH",
    ) -> None: ...

    def put_attribution(
        self,
        *,
        observation_id: str,
        feature_name: str,
        feature_value: float,
        feature_source: str,
        feature_freshness: str,
        feature_weight: float,
        regime: str,
        model: str,
        decision: str,
        outcome: str | None = None,
        realized_contribution: float | None = None,
        confidence: float = 0.0,
    ) -> None: ...


@dataclass(frozen=True)
class KalshiLearningFeature:
    name: str
    value: float
    freshness: str
    family: str
    category: str | None = None
    market_ticker: str | None = None
    exchange_index: str | None = None


_ALLOWED_PREFIX = "kalshi."


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def learning_features_from_observation(
    observation: Mapping[str, Any],
) -> list[KalshiLearningFeature]:
    """Normalize Kalshi research evidence into learner-safe feature records.

    The bridge is deliberately research-only: it creates namespaced features
    and never changes broker execution, strategy thresholds, risk limits, or
    model promotion state.
    """

    family = str(observation.get("family") or "predictions").strip().lower()
    if family not in {"predictions", "perps"}:
        return []
    freshness = str(observation.get("quality") or observation.get("freshness") or "UNKNOWN").upper()
    category = str(observation.get("category")) if observation.get("category") is not None else None
    ticker = str(observation.get("market_ticker") or observation.get("instrument") or "") or None
    exchange_index = str(observation.get("exchange_index")) if observation.get("exchange_index") is not None else None

    payload = observation.get("payload")
    values: Mapping[str, Any] = payload if isinstance(payload, Mapping) else observation
    features: list[KalshiLearningFeature] = []
    for raw_name, raw_value in values.items():
        name = str(raw_name)
        if not name.startswith(_ALLOWED_PREFIX):
            continue
        value = _finite(raw_value)
        if value is None:
            continue
        features.append(
            KalshiLearningFeature(
                name=name,
                value=value,
                freshness=freshness,
                family=family,
                category=category,
                market_ticker=ticker,
                exchange_index=exchange_index,
            )
        )
    return features


def persist_learning_features(
    sink: FeatureSink,
    *,
    observation_id: str,
    experiment_id: str,
    symbol: str,
    pillar: str,
    regime: str,
    features: Iterable[KalshiLearningFeature],
    confidence: float = 0.0,
) -> int:
    """Persist Kalshi features for attribution without granting broker control.

    All features enter with weight 0.0 and decision ``research_only``. This
    lets the platform measure correlation, calibration, lead/lag behavior, and
    eventual realized contribution before any challenger is allowed to use the
    features for trading decisions.
    """

    saved = 0
    bounded_confidence = max(0.0, min(float(confidence), 1.0))
    for feature in features:
        if not feature.name.startswith(_ALLOWED_PREFIX):
            continue
        sink.put_feature(
            name=feature.name,
            value=feature.value,
            source="kalshi",
            experiment_id=experiment_id,
            symbol=symbol,
            pillar=pillar,
            freshness=feature.freshness,
        )
        sink.put_attribution(
            observation_id=observation_id,
            feature_name=feature.name,
            feature_value=feature.value,
            feature_source="kalshi",
            feature_freshness=feature.freshness,
            feature_weight=0.0,
            regime=regime,
            model="kalshi_research_candidate_v1",
            decision="research_only",
            outcome=None,
            realized_contribution=None,
            confidence=bounded_confidence,
        )
        saved += 1
    return saved
