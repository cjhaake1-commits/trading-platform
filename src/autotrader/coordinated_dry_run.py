from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .audit import SQLiteAuditStore
from .capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL
from .coordinated_test import FIVE_PILLAR_BASELINE_VERSION
from .models import AuditEvent, PortfolioState, TradeProposal
from .risk import RiskContext, RiskEngine, RiskLimits
from .risk_stack import LayeredRiskStack


@dataclass(frozen=True)
class DryRunCandidate:
    pillar: str
    broker: str
    proposal: TradeProposal
    order_type: str
    target_price: float | None
    strategy_version: str
    reason: str


@dataclass(frozen=True)
class DryRunDecision:
    pillar: str
    broker: str
    instrument: str
    side: str
    intended_entry: float
    order_type: str
    quantity: float
    notional_exposure: float
    stop: float
    target: float | None
    dollars_at_risk: float
    pillar_risk_pct: float
    model_confidence: float
    model_version: str
    strategy_version: str
    risk_engine_status: str
    reason: str


class FivePillarDryRunner:
    """Pure no-submit evaluator; this module has no broker-order dependency."""

    def __init__(self, audit: SQLiteAuditStore | None = None) -> None:
        self.risk = LayeredRiskStack(RiskEngine())
        self.audit = audit

    def run(
        self,
        candidates: list[DryRunCandidate],
        *,
        portfolio: PortfolioState | None = None,
        deployed_by_pillar: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> list[DryRunDecision]:
        state = portfolio or PortfolioState(TOTAL_PAPER_CAPITAL, TOTAL_PAPER_CAPITAL)
        deployed = dict(deployed_by_pillar or {})
        gross = sum(abs(position.quantity * position.average_price) for position in state.positions.values())
        decisions = []
        approved_entries = 0
        for candidate in candidates:
            pillar_cap = PILLAR_ALLOCATIONS[candidate.pillar]
            pillar_deployed = deployed.get(candidate.pillar, 0.0)
            context = RiskContext(gross_notional=gross, asset_class_notional=pillar_deployed, peak_equity=state.equity)
            risk = self.risk.evaluate(candidate.proposal, state, risk_context=context)
            reason = risk.reason
            quantity = 0.0
            if candidate.proposal.stop_price <= 0:
                status, reason = "rejected", "Explicit stop/invalidation level is required"
            elif len(state.positions) + approved_entries >= RiskLimits().max_open_positions:
                status, reason = "rejected", "Maximum open positions reached"
            elif pillar_deployed >= pillar_cap:
                status, reason = "rejected", "Pillar allocation cap reached"
            elif not risk.approved:
                status = "rejected"
            else:
                allocation_room = max(pillar_cap - pillar_deployed, 0.0)
                reserve_room = max(state.cash - state.equity * 0.10, 0.0)
                pillar_risk = pillar_cap * RiskLimits().risk_per_trade_pct
                quantity = min(
                    risk.quantity,
                    allocation_room / candidate.proposal.entry_price,
                    reserve_room / candidate.proposal.entry_price,
                    pillar_risk / candidate.proposal.risk_per_unit,
                )
                if candidate.pillar != "alpaca_crypto":
                    quantity = float(int(quantity))
                else:
                    quantity = round(quantity, 8)
                status = "approved" if quantity > 0 else "rejected"
                if quantity <= 0:
                    reason = "No executable size within deterministic limits"
            notional = quantity * candidate.proposal.entry_price
            risk_dollars = quantity * candidate.proposal.risk_per_unit
            if status == "approved":
                deployed[candidate.pillar] = pillar_deployed + notional
                gross += notional
                approved_entries += 1
            decisions.append(
                DryRunDecision(
                    pillar=candidate.pillar,
                    broker=candidate.broker,
                    instrument=candidate.proposal.symbol,
                    side=candidate.proposal.side.value,
                    intended_entry=candidate.proposal.entry_price,
                    order_type=candidate.order_type,
                    quantity=quantity,
                    notional_exposure=notional,
                    stop=candidate.proposal.stop_price,
                    target=candidate.target_price,
                    dollars_at_risk=risk_dollars,
                    pillar_risk_pct=risk_dollars / pillar_cap if pillar_cap else 0.0,
                    model_confidence=candidate.proposal.confidence,
                    model_version=FIVE_PILLAR_BASELINE_VERSION,
                    strategy_version=candidate.strategy_version,
                    risk_engine_status=status,
                    reason=candidate.reason if status == "approved" else reason,
                )
            )
        if self.audit is not None:
            self.audit.append(
                AuditEvent(
                    "five_pillar_dry_run",
                    "Coordinated five-pillar no-submit dry run completed",
                    {
                        "baseline_version": FIVE_PILLAR_BASELINE_VERSION,
                        "orders_submitted": 0,
                        "manifest": [asdict(item) for item in decisions],
                    },
                    created_at=now or datetime.now(UTC),
                )
            )
        return decisions
