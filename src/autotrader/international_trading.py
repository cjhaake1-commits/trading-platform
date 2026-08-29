from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .brokers.saxo_sim import SaxoApprovedOrder, SaxoOrderResult, SaxoSimAdapter
from .capital_allocations import INTERNATIONAL_SIM_CAPITAL, PILLAR_INTERNATIONAL
from .models import PortfolioState, TradeProposal
from .risk import RiskContext, RiskEngine, RiskLimits
from .risk_stack import LayeredRiskStack, RiskStackDecision

INTERNATIONAL_CURRENT_FUND_ID = "paper-fund"
INTERNATIONAL_CURRENT_EPOCH = "international-current-fund-v1"
INTERNATIONAL_LEGACY_EPOCH = "international-legacy-pre-v1"


@dataclass(frozen=True)
class InternationalOrderSpec:
    proposal: TradeProposal
    account_key: str
    uic: int
    saxo_asset_type: str
    target_price: float | None = None
    model_version: str = "five_pillar_baseline_v1"
    strategy_version: str = "baseline-strategy-v1"
    market_regime: str | None = None


@dataclass(frozen=True)
class InternationalExecutionPolicy:
    allocation_cap: float = INTERNATIONAL_SIM_CAPITAL
    max_risk_per_trade_pct: float = RiskLimits().risk_per_trade_pct
    min_cash_reserve_pct: float = 0.10

    @classmethod
    def from_env(cls) -> InternationalExecutionPolicy:
        configured = _env_float("SAXO_MAX_RISK_PER_TRADE_PCT", RiskLimits().risk_per_trade_pct)
        reserve = _env_float("SAXO_MIN_CASH_RESERVE_PCT", 0.10)
        return cls(
            max_risk_per_trade_pct=min(configured, RiskLimits().risk_per_trade_pct),
            min_cash_reserve_pct=reserve,
        )

    def __post_init__(self) -> None:
        if self.allocation_cap != INTERNATIONAL_SIM_CAPITAL:
            raise ValueError("International allocation is hard-locked to $1,000")
        if not 0 < self.max_risk_per_trade_pct <= RiskLimits().risk_per_trade_pct:
            raise ValueError("International risk per trade must be positive and cannot exceed the global limit")
        if not 0 <= self.min_cash_reserve_pct < 1:
            raise ValueError("Cash reserve percentage must be between zero and one")


@dataclass(frozen=True)
class InternationalExecutionResult:
    approved: bool
    submitted: bool
    reason: str
    quantity: float = 0.0
    order_id: str | None = None
    trade_id: int | None = None


class SaxoOrderBroker(Protocol):
    def submit_order(self, order: SaxoApprovedOrder) -> SaxoOrderResult: ...


class LoggedOrderSpec(Protocol):
    proposal: TradeProposal
    target_price: float | None
    model_version: str
    strategy_version: str
    market_regime: str | None


class LoggedOrderResult(Protocol):
    ok: bool
    order_id: str | None
    message: str
    fill_price: float | None


class InternationalTradeHistory:
    """Append/update store used by audit, dashboard, and realized-outcome learning."""

    _ALLOWED_TABLES = {"international_trades", "metals_trades"}

    def __init__(
        self,
        path: str | Path,
        *,
        table_name: str = "international_trades",
        broker: str = "saxo-sim",
        pillar: str = PILLAR_INTERNATIONAL,
    ) -> None:
        if table_name not in self._ALLOWED_TABLES:
            raise ValueError("Unsupported trade-history table")
        self.path = Path(path)
        self.table_name = table_name
        self.broker = broker
        self.pillar = pillar
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposed_at TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    side TEXT NOT NULL,
                    proposed_entry REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    target_price REAL,
                    quantity REAL NOT NULL,
                    notional REAL NOT NULL,
                    model_confidence REAL NOT NULL,
                    model_version TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    market_regime TEXT,
                    risk_amount REAL NOT NULL DEFAULT 0,
                    risk_decision TEXT NOT NULL,
                    rejection_reason TEXT,
                    status TEXT NOT NULL,
                    order_id TEXT,
                    fill_price REAL,
                    exit_price REAL,
                    realized_pnl REAL,
                    fees_costs REAL NOT NULL DEFAULT 0,
                    opened_at TEXT,
                    closed_at TEXT,
                    holding_period_seconds REAL,
                    final_outcome TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    allocation_epoch TEXT NOT NULL DEFAULT '{INTERNATIONAL_LEGACY_EPOCH}'
                )
                """
            )
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({self.table_name})")}
            if "model_version" not in columns:
                connection.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN model_version TEXT NOT NULL "
                    "DEFAULT 'five_pillar_baseline_v1'"
                )
            if "market_regime" not in columns:
                connection.execute(f"ALTER TABLE {self.table_name} ADD COLUMN market_regime TEXT")
            if "risk_amount" not in columns:
                connection.execute(f"ALTER TABLE {self.table_name} ADD COLUMN risk_amount REAL NOT NULL DEFAULT 0")
            if "allocation_epoch" not in columns:
                # Existing provider-linked trades predate the current fund
                # boundary.  They remain durable evidence, but are legacy.
                connection.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN allocation_epoch TEXT NOT NULL "
                    f"DEFAULT '{INTERNATIONAL_LEGACY_EPOCH}'"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS international_fund_epoch ("
                "fund_id TEXT PRIMARY KEY, allocation_epoch TEXT NOT NULL, "
                "starting_capital REAL NOT NULL, created_at TEXT NOT NULL, active INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO international_fund_epoch "
                "(fund_id, allocation_epoch, starting_capital, created_at, active) VALUES (?, ?, ?, ?, 1)",
                (INTERNATIONAL_CURRENT_FUND_ID, INTERNATIONAL_CURRENT_EPOCH, INTERNATIONAL_SIM_CAPITAL,
                 datetime.now(UTC).isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def record_proposal(
        self,
        spec: LoggedOrderSpec,
        *,
        quantity: float,
        decision: str,
        rejection_reason: str | None,
        now: datetime,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO {self.table_name} (
                    proposed_at, broker, pillar, instrument, side, proposed_entry,
                    stop_price, target_price, quantity, notional, model_confidence,
                    model_version, strategy_version, market_regime, risk_amount,
                    risk_decision, rejection_reason, status, allocation_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.astimezone(UTC).isoformat(),
                    self.broker,
                    self.pillar,
                    spec.proposal.symbol,
                    spec.proposal.side.value,
                    spec.proposal.entry_price,
                    spec.proposal.stop_price,
                    spec.target_price,
                    quantity,
                    quantity * spec.proposal.entry_price,
                    spec.proposal.confidence,
                    spec.model_version,
                    spec.strategy_version,
                    spec.market_regime,
                    quantity * spec.proposal.risk_per_unit,
                    decision,
                    rejection_reason,
                    "rejected" if rejection_reason else "approved",
                    INTERNATIONAL_CURRENT_EPOCH,
                ),
            )
            return int(cursor.lastrowid)

    def record_submission(self, trade_id: int, result: LoggedOrderResult, *, now: datetime) -> None:
        costs = getattr(result, "estimated_costs", None)
        if costs is None:
            costs = getattr(result, "fees_costs", None)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE {self.table_name} SET
                    status = ?, order_id = ?, fill_price = ?, fees_costs = ?,
                    opened_at = ?, rejection_reason = ?
                WHERE id = ?
                """,
                (
                    "executed" if result.ok else "submission_failed",
                    result.order_id,
                    result.fill_price,
                    costs or 0.0,
                    now.astimezone(UTC).isoformat() if result.ok else None,
                    None if result.ok else result.message,
                    trade_id,
                ),
            )

    def record_close(
        self,
        trade_id: int,
        *,
        exit_price: float,
        realized_pnl: float,
        fees_costs: float = 0.0,
        final_outcome: str,
        now: datetime | None = None,
    ) -> None:
        closed_at = now or datetime.now(UTC)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT opened_at, fees_costs FROM {self.table_name} WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown international trade id")
            opened_at = datetime.fromisoformat(row["opened_at"]) if row["opened_at"] else closed_at
            holding = max((closed_at - opened_at).total_seconds(), 0.0)
            connection.execute(
                f"""
                UPDATE {self.table_name} SET status = 'closed', exit_price = ?,
                    realized_pnl = ?, fees_costs = ?, closed_at = ?,
                    holding_period_seconds = ?, final_outcome = ? WHERE id = ?
                """,
                (
                    exit_price,
                    realized_pnl,
                    float(row["fees_costs"] or 0.0) + fees_costs,
                    closed_at.astimezone(UTC).isoformat(),
                    holding,
                    final_outcome,
                    trade_id,
                ),
            )

    def records(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {self.table_name} ORDER BY id")]

    def learning_records(self) -> list[dict[str, object]]:
        return [row for row in self.records() if row["status"] == "closed"]

    def current_epoch_order_ids(self) -> set[str]:
        return {
            str(row["order_id"])
            for row in self.records()
            if row.get("allocation_epoch") == INTERNATIONAL_CURRENT_EPOCH
            and row.get("status") == "executed"
            and row.get("closed_at") is None
            and row.get("order_id")
        }

    def legacy_order_ids(self) -> set[str]:
        return {
            str(row["order_id"])
            for row in self.records()
            if row.get("allocation_epoch") != INTERNATIONAL_CURRENT_EPOCH and row.get("order_id")
        }


class InternationalExecutionService:
    def __init__(
        self,
        broker: SaxoOrderBroker,
        history: InternationalTradeHistory,
        *,
        risk_stack: LayeredRiskStack | None = None,
        policy: InternationalExecutionPolicy | None = None,
    ) -> None:
        self.broker = broker
        self.history = history
        self.policy = policy or InternationalExecutionPolicy.from_env()
        limits = RiskLimits(risk_per_trade_pct=self.policy.max_risk_per_trade_pct)
        self.risk_stack = risk_stack or LayeredRiskStack(RiskEngine(limits))

    @classmethod
    def from_env(cls, history_path: str | Path) -> InternationalExecutionService:
        return cls(SaxoSimAdapter.from_env(), InternationalTradeHistory(history_path))

    def execute(
        self,
        spec: InternationalOrderSpec,
        portfolio: PortfolioState,
        *,
        international_deployed: float,
        risk_context: RiskContext | None = None,
        now: datetime | None = None,
    ) -> InternationalExecutionResult:
        timestamp = now or datetime.now(UTC)
        effective_context = risk_context or self._portfolio_risk_context(spec, portfolio)
        decision = self.risk_stack.evaluate(spec.proposal, portfolio, risk_context=effective_context)
        rejection = self._rejection_reason(spec, portfolio, international_deployed, decision)
        quantity = self._approved_quantity(spec, portfolio, international_deployed, decision)
        if rejection is None and quantity <= 0:
            rejection = "No remaining international allocation or cash-reserve capacity"

        logged_quantity = quantity or spec.proposal.requested_quantity or 0.0
        trade_id = self.history.record_proposal(
            spec,
            quantity=logged_quantity,
            decision="approved" if rejection is None else "rejected",
            rejection_reason=rejection,
            now=timestamp,
        )
        if rejection is not None:
            return InternationalExecutionResult(False, False, rejection, trade_id=trade_id)

        order = SaxoApprovedOrder(
            account_key=spec.account_key,
            uic=spec.uic,
            asset_type=spec.saxo_asset_type,
            side=spec.proposal.side.value,
            quantity=quantity,
            stop_price=spec.proposal.stop_price,
            external_reference=f"intl-{trade_id}-{spec.strategy_version}"[:50],
            risk_approved=True,
        )
        result = self.broker.submit_order(order)
        self.history.record_submission(trade_id, result, now=timestamp)
        return InternationalExecutionResult(
            approved=True,
            submitted=result.ok,
            reason=result.message,
            quantity=quantity,
            order_id=result.order_id,
            trade_id=trade_id,
        )

    @staticmethod
    def _portfolio_risk_context(
        spec: InternationalOrderSpec,
        portfolio: PortfolioState,
    ) -> RiskContext:
        gross_notional = sum(
            abs(position.quantity * position.average_price) for position in portfolio.positions.values()
        )
        asset_class_notional = sum(
            abs(position.quantity * position.average_price)
            for position in portfolio.positions.values()
            if position.asset_class is spec.proposal.asset_class
        )
        return RiskContext(
            peak_equity=portfolio.equity,
            gross_notional=gross_notional,
            asset_class_notional=asset_class_notional,
        )

    def _rejection_reason(
        self,
        spec: InternationalOrderSpec,
        portfolio: PortfolioState,
        deployed: float,
        decision: RiskStackDecision,
    ) -> str | None:
        if spec.proposal.stop_price <= 0:
            return "Explicit stop/invalidation level is required"
        if not decision.approved:
            return decision.reason
        if deployed >= self.policy.allocation_cap:
            return "International pillar allocation cap reached"
        risk_dollars = decision.quantity * spec.proposal.risk_per_unit
        pillar_risk_cap = self.policy.allocation_cap * self.policy.max_risk_per_trade_pct
        if risk_dollars <= 0 or pillar_risk_cap <= 0:
            return "No international risk capacity"
        reserve = portfolio.equity * self.policy.min_cash_reserve_pct
        if portfolio.cash <= reserve:
            return "Portfolio cash reserve limit reached"
        return None

    def _approved_quantity(
        self,
        spec: InternationalOrderSpec,
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
        approved = min(
            decision.quantity,
            allocation_room / spec.proposal.entry_price,
            cash_room / spec.proposal.entry_price,
            pillar_risk / spec.proposal.risk_per_unit,
        )
        # Saxo SIM stock orders do not accept fractional share quantities.
        # Round down within the already-approved risk/capital envelope; a
        # result below one share remains rejected by the normal capacity path.
        if spec.saxo_asset_type.lower() == "stock":
            return float(int(approved))
        return approved


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
