from __future__ import annotations

from dataclasses import dataclass

from .correlation_risk import CorrelationAssessment, CorrelationBucketEngine
from .economic_events import EventRiskAssessment
from .models import PortfolioState, RiskDecision, TradeIntent, TradeProposal
from .open_risk import PortfolioOpenRisk, portfolio_open_risk
from .risk import RiskContext, RiskEngine


@dataclass(frozen=True)
class RiskStackPolicy:
    max_portfolio_open_risk_pct: float = 0.03
    min_scaled_quantity: float = 1e-12


@dataclass(frozen=True)
class RiskStackDecision:
    approved: bool
    reason: str
    quantity: float
    max_loss_dollars: float
    base: RiskDecision
    event: EventRiskAssessment | None = None
    correlation: CorrelationAssessment | None = None
    portfolio_open_risk: PortfolioOpenRisk | None = None


class LayeredRiskStack:
    """Compose independent safeguards without moving slow research into execution.

    Risk-reducing exits bypass new-exposure constraints. New entries must pass the
    base risk engine, scheduled-event controls, correlation concentration limits,
    and total open-risk budget.
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        *,
        correlation_engine: CorrelationBucketEngine | None = None,
        policy: RiskStackPolicy | None = None,
    ) -> None:
        self.risk_engine = risk_engine
        self.correlation_engine = correlation_engine
        self.policy = policy or RiskStackPolicy()

    def evaluate(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
        *,
        risk_context: RiskContext | None = None,
        event_risk: EventRiskAssessment | None = None,
        mark_prices: dict[str, float] | None = None,
    ) -> RiskStackDecision:
        base = self.risk_engine.evaluate(proposal, portfolio, risk_context)
        if not base.approved:
            return RiskStackDecision(False, base.reason, 0.0, 0.0, base)

        if proposal.intent in {TradeIntent.REDUCE, TradeIntent.EXIT}:
            return RiskStackDecision(
                True,
                "risk-reducing action approved",
                base.quantity,
                0.0,
                base,
                event=event_risk,
            )

        quantity = base.quantity
        if event_risk is not None:
            if event_risk.block_new_entries:
                return RiskStackDecision(
                    False,
                    event_risk.reason,
                    0.0,
                    0.0,
                    base,
                    event=event_risk,
                )
            quantity *= event_risk.risk_scale

        correlation = None
        if self.correlation_engine is not None:
            correlation = self.correlation_engine.assess(
                proposal,
                portfolio,
                proposed_quantity=quantity,
                mark_prices=mark_prices,
            )
            if correlation.blocked:
                return RiskStackDecision(
                    False,
                    correlation.reason,
                    0.0,
                    0.0,
                    base,
                    event=event_risk,
                    correlation=correlation,
                )
            quantity *= correlation.risk_scale

        open_risk = portfolio_open_risk(portfolio, mark_prices=mark_prices or {})
        current_open_risk = open_risk.total_open_risk_dollars
        max_open_risk = portfolio.equity * self.policy.max_portfolio_open_risk_pct
        per_unit_risk = proposal.risk_per_unit
        remaining = max(max_open_risk - current_open_risk, 0.0)
        if per_unit_risk > 0:
            quantity = min(quantity, remaining / per_unit_risk)

        if quantity <= self.policy.min_scaled_quantity:
            return RiskStackDecision(
                False,
                "portfolio open-risk budget exhausted",
                0.0,
                0.0,
                base,
                event=event_risk,
                correlation=correlation,
                portfolio_open_risk=open_risk,
            )

        return RiskStackDecision(
            True,
            "trade passed layered portfolio risk stack",
            quantity,
            quantity * per_unit_risk,
            base,
            event=event_risk,
            correlation=correlation,
            portfolio_open_risk=open_risk,
        )
