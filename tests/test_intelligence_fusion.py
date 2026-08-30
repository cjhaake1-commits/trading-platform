from datetime import UTC, datetime

from autotrader.intelligence_fusion import (
    CorporateFeatureSnapshot,
    IntelligenceFusionEngine,
    MarketConfirmationSnapshot,
)
from autotrader.social_market_intelligence import SocialMarketSnapshot


def test_game_stop_style_confluence_prioritizes_research_but_never_executes():
    now = datetime.now(UTC)
    social = SocialMarketSnapshot(
        symbol="XYZ",
        observed_at=now,
        mention_count=10000,
        unique_authors=5000,
        platforms=5,
        sentiment=0.8,
        attention_score=0.95,
        velocity_score=1.0,
        influencer_score=0.75,
        cross_platform_score=1.0,
        manipulation_risk=0.10,
        research_signal=0.9,
    )
    corporate = CorporateFeatureSnapshot(
        symbol="XYZ",
        observed_at=now,
        fundamental_quality=-0.3,
        fundamental_momentum=-0.4,
        leverage_risk=0.7,
        cashflow_quality=-0.2,
        filing_change_intensity=0.7,
    )
    market = MarketConfirmationSnapshot(
        symbol="XYZ",
        observed_at=now,
        price_momentum=0.9,
        relative_volume=1.0,
        volatility_expansion=0.9,
        short_interest_pressure=1.0,
        options_activity=0.95,
        liquidity_risk=0.2,
        cross_asset_confirmation=0.6,
    )

    result = IntelligenceFusionEngine().fuse(social, corporate, market, now=now)

    assert result.anomaly_priority > 0.6
    assert result.squeeze_context > 0.8
    assert result.execution_authorized is False
    assert "social attention anomaly" in result.reasons


def test_manipulation_risk_penalizes_priority():
    now = datetime.now(UTC)
    base = dict(
        symbol="XYZ",
        observed_at=now,
        mention_count=1000,
        unique_authors=10,
        platforms=1,
        sentiment=0.95,
        attention_score=0.95,
        velocity_score=1.0,
        influencer_score=0.3,
        cross_platform_score=0.25,
        research_signal=0.7,
    )
    corporate = CorporateFeatureSnapshot(symbol="XYZ", observed_at=now)
    market = MarketConfirmationSnapshot(
        symbol="XYZ", observed_at=now, price_momentum=0.7, relative_volume=0.8
    )
    engine = IntelligenceFusionEngine()
    clean = engine.fuse(SocialMarketSnapshot(**base, manipulation_risk=0.05), corporate, market)
    risky = engine.fuse(SocialMarketSnapshot(**base, manipulation_risk=0.95), corporate, market)

    assert risky.anomaly_priority < clean.anomaly_priority
    assert risky.execution_authorized is False
