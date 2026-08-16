from __future__ import annotations

from dataclasses import dataclass

from .models import PortfolioState, RiskDecision, Side, TradeIntent, TradeProposal


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_weekly_loss_pct: float = 0.05
    max_peak_drawdown_pct: float = 0.08
    soft_drawdown_pct: float = 0.04
    soft_drawdown_risk_scale: float = 0.50
    max_open_positions: int = 3
    max_position_notional_pct: float = 0.35
    max_gross_notional_pct: float = 1.00
    max_asset_class_notional_pct: float = 0.60
    min_confidence: float = 0.0
    allow_short_selling: bool = False
    allow_leverage: bool = False


@dataclass(frozen=True)
class RiskContext:
    peak_equity: float | None = None
    gross_notional: float = 0.0
    asset_class_notional: float = 0.0
    volatility_scale: float = 1.0
    correlation_scale: float = 1.0
    liquidity_scale: float = 1.0
    health_scale: float = 1.0

    def effective_scale(self) -> float:
        values = (
            self.volatility_scale,
            self.correlation_scale,
            self.liquidity_scale,
            self.health_scale,
        )
        if any(value < 0 for value in values):
            raise ValueError("risk context scales cannot be negative")
        return min(1.0, *values)


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
        context: RiskContext | None = None,
    ) -> RiskDecision:
        if portfolio.equity <= 0:
            return RiskDecision(False, "Account equity must be positive")

        if proposal.entry_price <= 0 or proposal.stop_price <= 0:
            return RiskDecision(False, "Entry and stop prices must be positive")

        position = portfolio.positions.get(proposal.symbol)
        if proposal.intent in {TradeIntent.REDUCE, TradeIntent.EXIT}:
            return self._evaluate_reduction(proposal, position)

        if proposal.confidence < self.limits.min_confidence:
            return RiskDecision(False, "Proposal confidence below risk threshold")

        if proposal.risk_per_unit <= 0:
            return RiskDecision(False, "Trade requires a non-zero stop distance")

        if proposal.side is Side.BUY and proposal.stop_price >= proposal.entry_price:
            return RiskDecision(False, "Long trade stop must be below entry")

        if proposal.side is Side.SELL:
            if not self.limits.allow_short_selling:
                return RiskDecision(False, "Short selling is disabled")
            if proposal.stop_price <= proposal.entry_price:
                return RiskDecision(False, "Short trade stop must be above entry")

        if proposal.intent is TradeIntent.INCREASE and position is None:
            return RiskDecision(False, "Cannot increase a position that does not exist")

        if proposal.intent is TradeIntent.ENTER and position is not None:
            return RiskDecision(False, "Position already exists; use INCREASE")

        if (
            proposal.intent is TradeIntent.ENTER
            and len(portfolio.positions) >= self.limits.max_open_positions
        ):
            return RiskDecision(False, "Maximum open positions reached")

        if portfolio.daily_pnl <= -(portfolio.equity * self.limits.max_daily_loss_pct):
            return RiskDecision(False, "Daily loss limit reached")

        if portfolio.weekly_pnl <= -(portfolio.equity * self.limits.max_weekly_loss_pct):
            return RiskDecision(False, "Weekly loss limit reached")

        context = context or RiskContext()
        drawdown_pct = self._drawdown_pct(portfolio.equity, context.peak_equity)
        if drawdown_pct >= self.limits.max_peak_drawdown_pct:
            return RiskDecision(False, "Maximum peak-to-trough drawdown reached")

        risk_scale = context.effective_scale()
        if drawdown_pct >= self.limits.soft_drawdown_pct:
            risk_scale = min(risk_scale, self.limits.soft_drawdown_risk_scale)

        if risk_scale <= 0:
            return RiskDecision(False, "Risk context disabled new exposure")

        max_loss = portfolio.equity * self.limits.risk_per_trade_pct * risk_scale
        quantity_by_risk = max_loss / proposal.risk_per_unit

        quantity = quantity_by_risk
        binding_constraint = "risk_per_trade"

        if not self.limits.allow_leverage:
            quantity_by_cash = portfolio.cash / proposal.entry_price
            if quantity_by_cash < quantity:
                quantity = quantity_by_cash
                binding_constraint = "cash"

        max_position_notional = portfolio.equity * self.limits.max_position_notional_pct
        existing_notional = 0.0
        if position is not None:
            existing_notional = position.quantity * proposal.entry_price
        position_room = max(max_position_notional - existing_notional, 0.0)
        quantity_by_position = position_room / proposal.entry_price
        if quantity_by_position < quantity:
            quantity = quantity_by_position
            binding_constraint = "position_notional"

        gross_limit = portfolio.equity * self.limits.max_gross_notional_pct
        gross_room = max(gross_limit - context.gross_notional, 0.0)
        quantity_by_gross = gross_room / proposal.entry_price
        if quantity_by_gross < quantity:
            quantity = quantity_by_gross
            binding_constraint = "gross_notional"

        asset_class_limit = portfolio.equity * self.limits.max_asset_class_notional_pct
        asset_class_room = max(asset_class_limit - context.asset_class_notional, 0.0)
        quantity_by_asset_class = asset_class_room / proposal.entry_price
        if quantity_by_asset_class < quantity:
            quantity = quantity_by_asset_class
            binding_constraint = "asset_class_notional"

        if proposal.requested_quantity is not None and proposal.requested_quantity < quantity:
            quantity = proposal.requested_quantity
            binding_constraint = "requested_quantity"

        if quantity <= 0:
            return RiskDecision(False, "No remaining risk capacity for proposed trade")

        return RiskDecision(
            approved=True,
            reason="Trade passed layered deterministic risk checks",
            quantity=quantity,
            max_loss_dollars=quantity * proposal.risk_per_unit,
            risk_scale=risk_scale,
            binding_constraint=binding_constraint,
        )

    @staticmethod
    def _drawdown_pct(equity: float, peak_equity: float | None) -> float:
        if peak_equity is None or peak_equity <= 0 or equity >= peak_equity:
            return 0.0
        return max((peak_equity - equity) / peak_equity, 0.0)

    def _evaluate_reduction(self, proposal: TradeProposal, position) -> RiskDecision:
        if position is None:
            return RiskDecision(False, "Cannot reduce or exit a position that does not exist")
        if proposal.side is not Side.SELL:
            return RiskDecision(False, "Long-position reduction requires SELL direction")
        if position.quantity <= 0:
            return RiskDecision(False, "Only long-position reductions are currently supported")

        if proposal.intent is TradeIntent.EXIT:
            quantity = position.quantity
        else:
            requested = proposal.requested_quantity
            if requested is None:
                return RiskDecision(False, "REDUCE requires requested_quantity")
            quantity = min(requested, position.quantity)

        if quantity <= 0:
            return RiskDecision(False, "Reduction quantity must be positive")

        return RiskDecision(
            approved=True,
            reason="Position reduction passed deterministic risk checks",
            quantity=quantity,
            max_loss_dollars=0.0,
            risk_scale=1.0,
            binding_constraint="risk_reduction",
        )
