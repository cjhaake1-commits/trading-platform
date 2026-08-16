from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .correlation_risk import CorrelationBucketPolicy
from .economic_events import EventRiskPolicy
from .protective_risk import ProtectiveRiskPolicy
from .risk import RiskLimits
from .risk_stack import RiskStackPolicy


class RiskProfileName(StrEnum):
    COMPETITIVE_PAPER = "competitive_paper"
    CONSERVATIVE_BASELINE = "conservative_baseline"


@dataclass(frozen=True)
class RiskProfile:
    name: RiskProfileName
    risk_limits: RiskLimits
    protective: ProtectiveRiskPolicy
    stack: RiskStackPolicy
    correlation: CorrelationBucketPolicy
    events: EventRiskPolicy


def competitive_paper_profile() -> RiskProfile:
    return RiskProfile(
        name=RiskProfileName.COMPETITIVE_PAPER,
        risk_limits=RiskLimits(),
        protective=ProtectiveRiskPolicy(),
        stack=RiskStackPolicy(),
        correlation=CorrelationBucketPolicy(),
        events=EventRiskPolicy(),
    )


def conservative_baseline_profile() -> RiskProfile:
    """Original bootstrap-style controls retained only as an A/B benchmark."""
    return RiskProfile(
        name=RiskProfileName.CONSERVATIVE_BASELINE,
        risk_limits=RiskLimits(
            risk_per_trade_pct=0.005,
            max_daily_loss_pct=0.02,
            max_weekly_loss_pct=0.05,
            max_peak_drawdown_pct=0.08,
            soft_drawdown_pct=0.04,
            soft_drawdown_risk_scale=0.50,
            max_open_positions=3,
            max_position_notional_pct=0.35,
            max_gross_notional_pct=1.00,
            max_asset_class_notional_pct=0.60,
            allow_short_selling=False,
            allow_leverage=False,
        ),
        protective=ProtectiveRiskPolicy(
            max_peak_drawdown_pct=0.08,
            hard_daily_loss_pct=0.02,
            hard_weekly_loss_pct=0.05,
            break_even_trigger_r=1.0,
            trailing_trigger_r=2.0,
            trailing_distance_r=1.0,
        ),
        stack=RiskStackPolicy(max_portfolio_open_risk_pct=0.03),
        correlation=CorrelationBucketPolicy(
            max_bucket_notional_pct=0.50,
            soft_bucket_notional_pct=0.35,
            soft_risk_scale=0.50,
        ),
        events=EventRiskPolicy(
            high_pre_seconds=300,
            high_post_seconds=180,
            medium_pre_seconds=120,
            medium_post_seconds=60,
            high_risk_scale=0.25,
            medium_risk_scale=0.60,
            block_new_entries_seconds=30,
        ),
    )
