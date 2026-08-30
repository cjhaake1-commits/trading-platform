from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import log1p
from statistics import fmean


class SocialPlatform(StrEnum):
    REDDIT = "reddit"
    X = "x"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    STOCKTWITS = "stocktwits"
    OTHER = "other"


@dataclass(frozen=True)
class SocialMention:
    """Point-in-time public social observation used for research only."""

    symbol: str
    platform: SocialPlatform
    author_id: str
    observed_at: datetime
    published_at: datetime
    text: str
    sentiment: float = 0.0
    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    source_url: str | None = None
    source_id: str | None = None
    commercial_use_authorized: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not -1.0 <= self.sentiment <= 1.0:
            raise ValueError("sentiment must be between -1 and 1")
        if self.observed_at.tzinfo is None or self.published_at.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")


@dataclass(frozen=True)
class InfluencerProfile:
    platform: SocialPlatform
    author_id: str
    display_name: str
    followers: int | None = None
    finance_relevance: float = 0.0
    historical_market_impact: float = 0.0
    identity_verified: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SocialMarketSnapshot:
    symbol: str
    observed_at: datetime
    mention_count: int
    unique_authors: int
    platforms: int
    sentiment: float
    attention_score: float
    velocity_score: float
    influencer_score: float
    cross_platform_score: float
    manipulation_risk: float
    research_signal: float
    notes: tuple[str, ...] = ()


class SocialMarketIntelligence:
    """Aggregate public social attention without creating execution authority.

    GameStop-style episodes are modeled as a confluence problem: attention and
    attention velocity are contextualized with market/fundamental features by
    downstream research. Social popularity alone must never create an order.
    """

    def summarize(
        self,
        symbol: str,
        mentions: list[SocialMention],
        *,
        prior_mention_count: int = 0,
        influencers: dict[tuple[SocialPlatform, str], InfluencerProfile] | None = None,
        now: datetime | None = None,
    ) -> SocialMarketSnapshot:
        now = now or datetime.now(UTC)
        symbol = symbol.upper()
        influencers = influencers or {}
        rows = [m for m in mentions if m.symbol.upper() == symbol and m.commercial_use_authorized]
        authors = {(m.platform, m.author_id) for m in rows}
        platforms = {m.platform for m in rows}
        sentiment = fmean([m.sentiment for m in rows]) if rows else 0.0

        engagement = 0.0
        influencer_weight = 0.0
        for row in rows:
            raw = sum(v or 0 for v in (row.views, row.likes, row.comments, row.shares))
            engagement += log1p(raw)
            profile = influencers.get((row.platform, row.author_id))
            if profile:
                follower_component = log1p(profile.followers or 0) / 20.0
                influencer_weight += min(
                    1.0,
                    0.35 * follower_component
                    + 0.30 * profile.finance_relevance
                    + 0.35 * profile.historical_market_impact,
                )

        attention = min(1.0, (log1p(len(rows)) + engagement / max(len(rows), 1)) / 12.0)
        velocity = 0.0
        if rows:
            velocity = max(-1.0, min(1.0, (len(rows) - prior_mention_count) / max(prior_mention_count, 1)))
        influencer_score = min(1.0, influencer_weight / max(len(rows), 1))
        cross_platform = min(1.0, len(platforms) / 4.0)

        # Concentrated authorship + extreme positive sentiment + weak cross-platform
        # confirmation is treated as manipulation/noise risk, not bullish evidence.
        concentration = 1.0 - min(1.0, len(authors) / max(len(rows), 1)) if rows else 0.0
        manipulation_risk = min(
            1.0,
            0.45 * concentration
            + 0.25 * max(sentiment, 0.0)
            + 0.30 * (1.0 - cross_platform),
        ) if rows else 0.0

        signal = (
            0.30 * attention
            + 0.25 * max(velocity, 0.0)
            + 0.20 * influencer_score
            + 0.15 * cross_platform
            + 0.10 * abs(sentiment)
        ) * (1.0 - 0.60 * manipulation_risk)

        notes: list[str] = []
        if mentions and not rows:
            notes.append("mentions excluded until source/commercial-use authorization is confirmed")
        if manipulation_risk >= 0.60:
            notes.append("high manipulation/noise risk; social signal must be corroborated")

        return SocialMarketSnapshot(
            symbol=symbol,
            observed_at=now,
            mention_count=len(rows),
            unique_authors=len(authors),
            platforms=len(platforms),
            sentiment=sentiment,
            attention_score=attention,
            velocity_score=velocity,
            influencer_score=influencer_score,
            cross_platform_score=cross_platform,
            manipulation_risk=manipulation_risk,
            research_signal=max(0.0, min(1.0, signal)),
            notes=tuple(notes),
        )
