from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .brokers.connectivity import ConnectivityResult, test_alpaca_paper, test_oanda_practice
from .brokers.safety import BrokerSafetyResult, alpaca_open_positions, oanda_open_positions
from .execution_safety import IdempotencyStore
from .models import PortfolioState
from .portfolio_ledger import PortfolioLedger
from .reconciliation import (
    PositionReconciler,
    ReconciliationResult,
    normalize_alpaca_positions,
    normalize_oanda_positions,
)
from .risk_profiles import RiskProfile, competitive_paper_profile


@dataclass(frozen=True)
class PreflightReport:
    ready: bool
    checks: dict[str, bool]
    reconciliation: ReconciliationResult
    portfolio: PortfolioState
    peak_equity: float
    profile: RiskProfile
    alpaca_connectivity: ConnectivityResult
    oanda_connectivity: ConnectivityResult
    alpaca_positions: BrokerSafetyResult | None
    oanda_positions: BrokerSafetyResult | None
    messages: tuple[str, ...] = ()

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.checks.items() if not ok)


def run_preflight(
    *,
    ledger_path: str | Path = "var/autotrader/portfolio.db",
    idempotency_path: str | Path = "var/autotrader/idempotency.db",
    initial_equity: float = 2000.0,
) -> PreflightReport:
    """Run a read-only broker preflight plus local persistence initialization.

    This function never submits, cancels, modifies, or closes a broker order or
    position. It is safe to call before a manually confirmed practice test.
    """

    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")

    ledger = PortfolioLedger(Path(ledger_path))
    IdempotencyStore(Path(idempotency_path))

    loaded = ledger.load_portfolio()
    if loaded is None:
        portfolio = PortfolioState(equity=initial_equity, cash=initial_equity)
        peak_equity = initial_equity
        ledger.save_portfolio(portfolio, peak_equity=peak_equity)
    else:
        portfolio, peak_equity = loaded

    alpaca_connectivity = test_alpaca_paper()
    oanda_connectivity = test_oanda_practice()

    messages: list[str] = []
    alpaca_positions: BrokerSafetyResult | None = None
    oanda_positions: BrokerSafetyResult | None = None

    if alpaca_connectivity.ok:
        try:
            alpaca_positions = alpaca_open_positions()
        except RuntimeError as exc:
            messages.append(f"Alpaca position read failed: {exc}")

    if oanda_connectivity.ok:
        try:
            oanda_positions = oanda_open_positions()
        except RuntimeError as exc:
            messages.append(f"OANDA position read failed: {exc}")

    broker_positions = []
    if alpaca_positions is not None and alpaca_positions.ok:
        broker_positions.extend(
            normalize_alpaca_positions(alpaca_positions.details.get("positions", []))
        )
    if oanda_positions is not None and oanda_positions.ok:
        broker_positions.extend(
            normalize_oanda_positions(oanda_positions.details.get("positions", []))
        )

    reconciliation = PositionReconciler().reconcile(portfolio, broker_positions)
    profile = competitive_paper_profile()

    account_ids = oanda_connectivity.details.get("account_ids", [])
    if not isinstance(account_ids, list):
        account_ids = []
    configured_oanda_account = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
    oanda_selection_unambiguous = bool(configured_oanda_account) or len(account_ids) == 1

    alpaca_status = str(alpaca_connectivity.details.get("status") or "").upper()
    alpaca_account_active = alpaca_connectivity.ok and alpaca_status in {"ACTIVE", "ACCOUNT_UPDATED"}
    # Some paper account responses omit or evolve status labels. Authentication
    # plus readable positions remains the authoritative operational check; an
    # empty status therefore does not fail preflight by itself.
    if alpaca_connectivity.ok and not alpaca_status:
        alpaca_account_active = True

    checks = {
        "alpaca_connectivity": alpaca_connectivity.ok,
        "alpaca_account_active": alpaca_account_active,
        "oanda_connectivity": oanda_connectivity.ok,
        "oanda_account_selection_unambiguous": oanda_selection_unambiguous,
        "broker_positions_readable": (
            alpaca_positions is not None
            and alpaca_positions.ok
            and oanda_positions is not None
            and oanda_positions.ok
        ),
        "ledger_initialized": ledger.load_portfolio() is not None,
        "reconciliation_ok": reconciliation.ok,
        "idempotency_store_initialized": Path(idempotency_path).exists(),
        "live_trading_disabled_by_preflight": True,
    }
    ready = all(checks.values())

    if not oanda_selection_unambiguous:
        messages.append(
            "Multiple or zero OANDA practice accounts are visible; set OANDA_PRACTICE_ACCOUNT_ID explicitly."
        )
    if not reconciliation.ok:
        messages.append(reconciliation.reason)

    return PreflightReport(
        ready=ready,
        checks=checks,
        reconciliation=reconciliation,
        portfolio=portfolio,
        peak_equity=peak_equity,
        profile=profile,
        alpaca_connectivity=alpaca_connectivity,
        oanda_connectivity=oanda_connectivity,
        alpaca_positions=alpaca_positions,
        oanda_positions=oanda_positions,
        messages=tuple(messages),
    )
