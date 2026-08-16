from __future__ import annotations

from dataclasses import dataclass, field

from autotrader.models import (
    PortfolioState,
    Position,
    RiskDecision,
    Side,
    TradeIntent,
    TradeProposal,
)


@dataclass
class PaperBroker:
    portfolio: PortfolioState
    fills: list[dict] = field(default_factory=list)

    def execute(self, proposal: TradeProposal, decision: RiskDecision) -> dict:
        if not decision.approved:
            raise ValueError("Risk decision rejected the trade")
        if decision.quantity <= 0:
            raise ValueError("Approved trade requires positive quantity")

        if proposal.intent in {TradeIntent.REDUCE, TradeIntent.EXIT}:
            return self._reduce_long(proposal, decision)
        return self._add_long(proposal, decision)

    def _add_long(self, proposal: TradeProposal, decision: RiskDecision) -> dict:
        if proposal.side is not Side.BUY:
            raise ValueError("Paper broker only supports long entries/increases for now")

        quantity = decision.quantity
        notional = quantity * proposal.entry_price
        if notional > self.portfolio.cash:
            raise ValueError("Paper broker refuses leveraged fill")

        existing = self.portfolio.positions.get(proposal.symbol)
        if proposal.intent is TradeIntent.ENTER and existing is not None:
            raise ValueError("Position already exists; use INCREASE")
        if proposal.intent is TradeIntent.INCREASE and existing is None:
            raise ValueError("Cannot increase a missing position")

        self.portfolio.cash -= notional
        if existing is None:
            position = Position(
                symbol=proposal.symbol,
                asset_class=proposal.asset_class,
                quantity=quantity,
                average_price=proposal.entry_price,
                stop_price=proposal.stop_price,
            )
            self.portfolio.positions[proposal.symbol] = position
        else:
            total_quantity = existing.quantity + quantity
            weighted_cost = (
                existing.average_price * existing.quantity + proposal.entry_price * quantity
            )
            existing.average_price = weighted_cost / total_quantity
            existing.quantity = total_quantity
            existing.stop_price = proposal.stop_price

        return self._record_fill(proposal, quantity, notional, realized_pnl=0.0)

    def _reduce_long(self, proposal: TradeProposal, decision: RiskDecision) -> dict:
        position = self.portfolio.positions.get(proposal.symbol)
        if position is None:
            raise ValueError("Cannot reduce a missing position")
        if proposal.side is not Side.SELL:
            raise ValueError("Long-position reduction requires SELL direction")

        quantity = min(decision.quantity, position.quantity)
        proceeds = quantity * proposal.entry_price
        realized_pnl = quantity * (proposal.entry_price - position.average_price)
        self.portfolio.cash += proceeds
        self.portfolio.daily_pnl += realized_pnl
        self.portfolio.weekly_pnl += realized_pnl
        position.realized_pnl += realized_pnl
        position.quantity -= quantity

        if position.quantity <= 1e-12 or proposal.intent is TradeIntent.EXIT:
            self.portfolio.positions.pop(proposal.symbol, None)

        return self._record_fill(proposal, quantity, proceeds, realized_pnl=realized_pnl)

    def _record_fill(
        self,
        proposal: TradeProposal,
        quantity: float,
        notional: float,
        *,
        realized_pnl: float,
    ) -> dict:
        fill = {
            "symbol": proposal.symbol,
            "side": proposal.side.value,
            "intent": proposal.intent.value,
            "quantity": quantity,
            "price": proposal.entry_price,
            "notional": notional,
            "realized_pnl": realized_pnl,
            "source": proposal.source,
        }
        self.fills.append(fill)
        return fill
