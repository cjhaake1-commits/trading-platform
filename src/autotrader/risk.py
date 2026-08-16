from __future__ import annotations

from dataclasses import dataclass

from .models import PortfolioState, RiskDecision, Side, TradeProposal


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_weekly_loss_pct: float = 0.05
    max_open_positions: int = 3
    allow_short_selling: bool = False
    allow_leverage: bool = False


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def evaluate(self, proposal: TradeProposal, portfolio: PortfolioState) -> RiskDecision:
        if portfolio.equity <= 0:
            return RiskDecision(False, "Account equity must be positive")

        if proposal.entry_price <= 0 or proposal.stop_price <= 0:
            return RiskDecision(False, "Entry and stop prices must be positive")

        if proposal.risk_per_unit <= 0:
            return RiskDecision(False, "Trade requires a non-zero stop distance")

        if proposal.side is Side.BUY and proposal.stop_price >= proposal.entry_price:
            return RiskDecision(False, "Long trade stop must be below entry")

        if proposal.side is Side.SELL:
            if not self.limits.allow_short_selling:
                return RiskDecision(False, "Short selling is disabled")
            if proposal.stop_price <= proposal.entry_price:
                return RiskDecision(False, "Short trade stop must be above entry")

        if len(portfolio.positions) >= self.limits.max_open_positions:
            return RiskDecision(False, "Maximum open positions reached")

        if portfolio.daily_pnl <= -(portfolio.equity * self.limits.max_daily_loss_pct):
            return RiskDecision(False, "Daily loss limit reached")

        if portfolio.weekly_pnl <= -(portfolio.equity * self.limits.max_weekly_loss_pct):
            return RiskDecision(False, "Weekly loss limit reached")

        max_loss = portfolio.equity * self.limits.risk_per_trade_pct
        quantity_by_risk = max_loss / proposal.risk_per_unit

        if self.limits.allow_leverage:
            quantity = quantity_by_risk
        else:
            quantity_by_cash = portfolio.cash / proposal.entry_price
            quantity = min(quantity_by_risk, quantity_by_cash)

        if quantity <= 0:
            return RiskDecision(False, "Insufficient cash for proposed trade")

        return RiskDecision(
            approved=True,
            reason="Trade passed deterministic risk checks",
            quantity=quantity,
            max_loss_dollars=quantity * proposal.risk_per_unit,
        )
