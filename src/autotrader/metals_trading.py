from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .brokers.alpaca_metals_paper import (
    METALS_UNIVERSE,
    AlpacaApprovedMetalsOrder,
    AlpacaMetalsOrderResult,
    AlpacaMetalsPaperAdapter,
)
from .capital_allocations import METALS_PAPER_CAPITAL, PILLAR_METALS
from .international_trading import InternationalTradeHistory
from .models import PortfolioState, TradeProposal
from .risk import RiskContext, RiskEngine, RiskLimits
from .risk_stack import LayeredRiskStack, RiskStackDecision


@dataclass(frozen=True)
class MetalsOrderSpec:
    proposal: TradeProposal
    target_price: float | None = None
    model_version: str = "five_pillar_baseline_v1"
    strategy_version: str = "baseline-strategy-v1"
    market_regime: str | None = None


@dataclass(frozen=True)
class MetalsExecutionPolicy:
    allocation_cap: float = METALS_PAPER_CAPITAL
    max_risk_per_trade_pct: float = RiskLimits().risk_per_trade_pct
    min_cash_reserve_pct: float = 0.10

    @classmethod
    def from_env(cls) -> MetalsExecutionPolicy:
        configured = _env_float("METALS_MAX_RISK_PER_TRADE_PCT", RiskLimits().risk_per_trade_pct)
        reserve = _env_float("METALS_MIN_CASH_RESERVE_PCT", 0.10)
        return cls(
            max_risk_per_trade_pct=min(configured, RiskLimits().risk_per_trade_pct),
            min_cash_reserve_pct=reserve,
        )

    def __post_init__(self) -> None:
        if self.allocation_cap != METALS_PAPER_CAPITAL:
            raise ValueError("Metals allocation is hard-locked to $1,000")
        if not 0 < self.max_risk_per_trade_pct <= RiskLimits().risk_per_trade_pct:
            raise ValueError("Metals risk per trade must be positive and cannot exceed the global limit")
        if not 0 <= self.min_cash_reserve_pct < 1:
            raise ValueError("Cash reserve percentage must be between zero and one")


@dataclass(frozen=True)
class MetalsExecutionResult:
    approved: bool
    submitted: bool
    reason: str
    quantity: float = 0.0
    order_id: str | None = None
    trade_id: int | None = None


class MetalsOrderBroker(Protocol):
    def is_tradable(self, symbol: str) -> bool: ...

    def submit_order(self, order: AlpacaApprovedMetalsOrder) -> AlpacaMetalsOrderResult: ...


class MetalsTradeHistory(InternationalTradeHistory):
    def __init__(self, path: str | Path) -> None:
        super().__init__(
            path,
            table_name="metals_trades",
            broker="alpaca-metals-paper",
            pillar=PILLAR_METALS,
        )


class MetalsExecutionService:
    """Deterministic risk and audit boundary for Alpaca PAPER metals orders."""

    def __init__(
        self,
        broker: MetalsOrderBroker,
        history: MetalsTradeHistory,
        *,
        risk_stack: LayeredRiskStack | None = None,
        policy: MetalsExecutionPolicy | None = None,
    ) -> None:
        self.broker = broker
        self.history = history
        self.policy = policy or MetalsExecutionPolicy.from_env()
        limits = RiskLimits(risk_per_trade_pct=self.policy.max_risk_per_trade_pct)
        self.risk_stack = risk_stack or LayeredRiskStack(RiskEngine(limits))

    @classmethod
    def from_env(cls, history_path: str | Path) -> MetalsExecutionService:
        return cls(AlpacaMetalsPaperAdapter.from_env(), MetalsTradeHistory(history_path))

    def execute(
        self,
        spec: MetalsOrderSpec,
        portfolio: PortfolioState,
        *,
        metals_deployed: float,
        risk_context: RiskContext | None = None,
        now: datetime | None = None,
    ) -> MetalsExecutionResult:
        timestamp = now or datetime.now(UTC)
        effective_context = risk_context or self._portfolio_risk_context(spec, portfolio)
        decision = self.risk_stack.evaluate(spec.proposal, portfolio, risk_context=effective_context)
        rejection = self._risk_rejection(spec, portfolio, metals_deployed, decision)
        if rejection is None and not self.broker.is_tradable(spec.proposal.symbol):
            rejection = "Instrument is not currently active and tradable on Alpaca paper"

        quantity = self._approved_quantity(spec, portfolio, metals_deployed, decision)
        if rejection is None and quantity < 1:
            rejection = "No whole-share capacity within metals risk and allocation limits"
        logged_quantity = quantity or spec.proposal.requested_quantity or 0.0
        trade_id = self.history.record_proposal(
            spec,
            quantity=logged_quantity,
            decision="approved" if rejection is None else "rejected",
            rejection_reason=rejection,
            now=timestamp,
        )
        if rejection is not None:
            return MetalsExecutionResult(False, False, rejection, trade_id=trade_id)

        order = AlpacaApprovedMetalsOrder(
            symbol=spec.proposal.symbol,
            side=spec.proposal.side.value,
            quantity=quantity,
            stop_price=spec.proposal.stop_price,
            target_price=spec.target_price,
            client_order_id=f"metals-{trade_id}-{spec.strategy_version}"[:48],
            risk_approved=True,
        )
        result = self.broker.submit_order(order)
        self.history.record_submission(trade_id, result, now=timestamp)
        return MetalsExecutionResult(
            approved=True,
            submitted=result.ok,
            reason=result.message,
            quantity=quantity,
            order_id=result.order_id,
            trade_id=trade_id,
        )

    @staticmethod
    def _portfolio_risk_context(spec: MetalsOrderSpec, portfolio: PortfolioState) -> RiskContext:
        gross = sum(abs(position.quantity * position.average_price) for position in portfolio.positions.values())
        asset_class = sum(
            abs(position.quantity * position.average_price)
            for position in portfolio.positions.values()
            if position.asset_class is spec.proposal.asset_class
        )
        return RiskContext(
            peak_equity=portfolio.equity,
            gross_notional=gross,
            asset_class_notional=asset_class,
        )

    def _risk_rejection(
        self,
        spec: MetalsOrderSpec,
        portfolio: PortfolioState,
        deployed: float,
        decision: RiskStackDecision,
    ) -> str | None:
        if spec.proposal.stop_price <= 0:
            return "Explicit stop/invalidation level is required"
        if spec.proposal.symbol.strip().upper() not in METALS_UNIVERSE:
            return "Instrument is outside the approved metals universe"
        if not decision.approved:
            return decision.reason
        if deployed >= self.policy.allocation_cap:
            return "Metals/Commodities pillar allocation cap reached"
        reserve = portfolio.equity * self.policy.min_cash_reserve_pct
        if portfolio.cash <= reserve:
            return "Portfolio cash reserve limit reached"
        return None

    def _approved_quantity(
        self,
        spec: MetalsOrderSpec,
        portfolio: PortfolioState,
        deployed: float,
        decision: RiskStackDecision,
    ) -> float:
        if not decision.approved or spec.proposal.entry_price <= 0 or spec.proposal.risk_per_unit <= 0:
            return 0.0
        allocation_room = max(self.policy.allocation_cap - deployed, 0.0)
        reserve = portfolio.equity * self.policy.min_cash_reserve_pct
        cash_room = max(portfolio.cash - reserve, 0.0)
        pillar_risk = self.policy.allocation_cap * self.policy.max_risk_per_trade_pct
        return float(
            math.floor(
                min(
                    decision.quantity,
                    allocation_room / spec.proposal.entry_price,
                    cash_room / spec.proposal.entry_price,
                    pillar_risk / spec.proposal.risk_per_unit,
                )
            )
        )


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
