from __future__ import annotations

from dataclasses import dataclass, field

from autotrader.models import PortfolioState, Position, RiskDecision, TradeProposal


@dataclass
class PaperBroker:
    portfolio: PortfolioState
    fills: list[dict] = field(default_factory=list)

    def execute(self, proposal: TradeProposal, decision: RiskDecision) -> dict:
        if not decision.approved:
            raise ValueError("Risk decision rejected the trade")

        notional = decision.quantity * proposal.entry_price
        if notional > self.portfolio.cash:
            raise ValueError("Paper broker refuses leveraged fill")

        self.portfolio.cash -= notional
        self.portfolio.positions[proposal.symbol] = Position(
            symbol=proposal.symbol,
            asset_class=proposal.asset_class,
            quantity=decision.quantity,
            average_price=proposal.entry_price,
            stop_price=proposal.stop_price,
        )

        fill = {
            "symbol": proposal.symbol,
            "side": proposal.side.value,
            "quantity": decision.quantity,
            "price": proposal.entry_price,
            "notional": notional,
            "source": proposal.source,
        }
        self.fills.append(fill)
        return fill
