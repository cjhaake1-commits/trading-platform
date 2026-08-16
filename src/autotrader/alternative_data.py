from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import exp, log


class AlternativeSource(StrEnum):
    NEWS = "news"
    SOCIAL = "social"
    PUBLIC_OFFICIAL_ACTIVITY = "public_official_activity"


@dataclass(frozen=True)
class AlternativeSignalItem:
    """Normalized alternative-data observation.

    score is directional market sentiment in [-1, 1]. confidence is source/model
    confidence in [0, 1]. Public-official activity is excluded unless the data
    provider has been explicitly approved for the intended commercial use.
    """

    symbol: str
    source: AlternativeSource
    observed_at: datetime
    score: float
    confidence: float
    text: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    commercial_use_authorized: bool = True

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError("score must be between -1 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True)
class AlternativeSignalContext:
    symbol: str
    combined_score: float
    news_score: float | None
    social_score: float | None
    public_official_score: float | None
    included_items: int
    excluded_items: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlternativeSignalConfig:
    news_half_life_hours: float = 18.0
    social_half_life_hours: float = 6.0
    public_official_half_life_hours: float = 24.0 * 14.0
    news_weight: float = 0.45
    social_weight: float = 0.35
    public_official_weight: float = 0.20


class AlternativeSignalEngine:
    """Fuse licensed news, social, and public-official activity into one feature.

    This layer is deliberately separate from execution. It creates context for
    TradingAgents and the deterministic fusion/risk layers; it cannot place an
    order itself.
    """

    def __init__(self, config: AlternativeSignalConfig | None = None):
        self.config = config or AlternativeSignalConfig()

    def summarize(
        self,
        symbol: str,
        items: list[AlternativeSignalItem],
        *,
        now: datetime | None = None,
    ) -> AlternativeSignalContext:
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        symbol = symbol.upper()
        grouped: dict[AlternativeSource, list[AlternativeSignalItem]] = {
            source: [] for source in AlternativeSource
        }
        excluded = 0
        notes: list[str] = []

        for item in items:
            if item.symbol.upper() != symbol:
                continue
            if (
                item.source is AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY
                and not item.commercial_use_authorized
            ):
                excluded += 1
                notes.append("excluded unapproved public-official data")
                continue
            grouped[item.source].append(item)

        components = {
            AlternativeSource.NEWS: self._weighted_score(
                grouped[AlternativeSource.NEWS], now, self.config.news_half_life_hours
            ),
            AlternativeSource.SOCIAL: self._weighted_score(
                grouped[AlternativeSource.SOCIAL], now, self.config.social_half_life_hours
            ),
            AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY: self._weighted_score(
                grouped[AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY],
                now,
                self.config.public_official_half_life_hours,
            ),
        }
        source_weights = {
            AlternativeSource.NEWS: self.config.news_weight,
            AlternativeSource.SOCIAL: self.config.social_weight,
            AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY: self.config.public_official_weight,
        }

        numerator = 0.0
        denominator = 0.0
        for source, value in components.items():
            if value is None:
                continue
            weight = source_weights[source]
            numerator += value * weight
            denominator += weight

        combined = numerator / denominator if denominator else 0.0
        included = sum(len(group) for group in grouped.values())

        return AlternativeSignalContext(
            symbol=symbol,
            combined_score=max(-1.0, min(1.0, combined)),
            news_score=components[AlternativeSource.NEWS],
            social_score=components[AlternativeSource.SOCIAL],
            public_official_score=components[AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY],
            included_items=included,
            excluded_items=excluded,
            notes=tuple(dict.fromkeys(notes)),
        )

    @staticmethod
    def _weighted_score(
        items: list[AlternativeSignalItem],
        now: datetime,
        half_life_hours: float,
    ) -> float | None:
        if not items:
            return None
        if half_life_hours <= 0:
            raise ValueError("half-life must be positive")

        numerator = 0.0
        denominator = 0.0
        decay_constant = log(2.0) / half_life_hours
        for item in items:
            age_hours = max((now - item.observed_at).total_seconds() / 3600.0, 0.0)
            recency = exp(-decay_constant * age_hours)
            weight = item.confidence * recency
            numerator += item.score * weight
            denominator += weight

        if denominator == 0.0:
            return None
        return max(-1.0, min(1.0, numerator / denominator))
