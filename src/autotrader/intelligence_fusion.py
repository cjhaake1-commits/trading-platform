from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from autotrader.social_market_intelligence import SocialMarketSnapshot


@dataclass(frozen=True)
class CorporateFeatureSnapshot:
    symbol: str
    observed_at: datetime
    fundamental_quality: float = 0.0
    fundamental_momentum: float = 0.0
    leverage_risk: float = 0.0
    cashflow_quality: float = 0.0
    capex_intensity: float = 0.0
    filing_change_intensity: float = 0.0
    constituent_deterioration: float = 0.0
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketConfirmationSnapshot:
    symbol: str
    observed_at: datetime
    price_momentum: float = 0.0
    relative_volume: float = 0.0
    volatility_expansion: float = 0.0
    short_interest_pressure: float = 0.0
    options_activity: float = 0.0
    liquidity_risk: float = 0.0
    cross_asset_confirmation: float = 0.0


@dataclass(frozen=True)
class IntelligenceFusionSnapshot:
    symbol: str
    observed_at: datetime
    attention_anomaly: float
    fundamental_context: float
    market_confirmation: float
    squeeze_context: float
    anomaly_priority: float
    manipulation_risk: float
    execution_authorized: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


class IntelligenceFusionEngine:
    """Fuse research contexts while preserving execution isolation.

    The result prioritizes hypotheses/experiments. It deliberately has no broker
    or order interface. Social attention cannot independently authorize a trade.
    """

    def fuse(
        self,
        social: SocialMarketSnapshot,
        corporate: CorporateFeatureSnapshot,
        market: MarketConfirmationSnapshot,
        *,
        now: datetime | None = None,
    ) -> IntelligenceFusionSnapshot:
        if not (social.symbol.upper() == corporate.symbol.upper() == market.symbol.upper()):
            raise ValueError("all snapshots must refer to the same symbol")
        now = now or datetime.now(UTC)

        attention = max(
            0.0,
            min(
                1.0,
                0.45 * social.attention_score
                + 0.30 * max(social.velocity_score, 0.0)
                + 0.15 * social.cross_platform_score
                + 0.10 * social.influencer_score,
            ),
        )
        fundamental = max(
            -1.0,
            min(
                1.0,
                0.30 * corporate.fundamental_quality
                + 0.25 * corporate.fundamental_momentum
                + 0.25 * corporate.cashflow_quality
                - 0.20 * corporate.leverage_risk,
            ),
        )
        confirmation = max(
            0.0,
            min(
                1.0,
                0.30 * max(market.price_momentum, 0.0)
                + 0.25 * market.relative_volume
                + 0.15 * market.volatility_expansion
                + 0.15 * market.options_activity
                + 0.15 * market.cross_asset_confirmation,
            ),
        )
        squeeze = max(
            0.0,
            min(
                1.0,
                0.40 * market.short_interest_pressure
                + 0.25 * market.options_activity
                + 0.20 * market.relative_volume
                + 0.15 * attention,
            ),
        )
        priority = (
            0.34 * attention
            + 0.30 * confirmation
            + 0.18 * squeeze
            + 0.10 * abs(fundamental)
            + 0.08 * corporate.filing_change_intensity
        )
        priority *= 1.0 - 0.65 * social.manipulation_risk
        priority *= 1.0 - 0.30 * market.liquidity_risk

        reasons: list[str] = []
        if attention >= 0.65:
            reasons.append("social attention anomaly")
        if confirmation >= 0.65:
            reasons.append("market activity confirms attention")
        if squeeze >= 0.65:
            reasons.append("short/options/volume squeeze context elevated")
        if corporate.filing_change_intensity >= 0.60:
            reasons.append("recent corporate filing change is material to research")
        if social.manipulation_risk >= 0.60:
            reasons.append("social manipulation/noise risk elevated")
        if market.liquidity_risk >= 0.60:
            reasons.append("liquidity risk elevated")

        return IntelligenceFusionSnapshot(
            symbol=social.symbol.upper(),
            observed_at=now,
            attention_anomaly=attention,
            fundamental_context=fundamental,
            market_confirmation=confirmation,
            squeeze_context=squeeze,
            anomaly_priority=max(0.0, min(1.0, priority)),
            manipulation_risk=social.manipulation_risk,
            execution_authorized=False,
            reasons=tuple(reasons),
        )
