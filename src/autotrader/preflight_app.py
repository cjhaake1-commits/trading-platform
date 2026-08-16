from __future__ import annotations

import argparse
import json
from pathlib import Path

from .brokers.connectivity import test_alpaca_paper, test_oanda_practice
from .brokers.safety import alpaca_open_positions, oanda_open_positions
from .execution_safety import IdempotencyStore
from .models import PortfolioState
from .portfolio_ledger import PortfolioLedger
from .reconciliation import (
    PositionReconciler,
    normalize_alpaca_positions,
    normalize_oanda_positions,
)
from .risk_profiles import competitive_paper_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only broker and safety preflight")
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--idempotency", default="var/autotrader/idempotency.db")
    parser.add_argument("--initial-equity", type=float, default=2000.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ledger = PortfolioLedger(Path(args.ledger))
    IdempotencyStore(Path(args.idempotency))

    loaded = ledger.load_portfolio()
    if loaded is None:
        portfolio = PortfolioState(equity=args.initial_equity, cash=args.initial_equity)
        peak_equity = args.initial_equity
        ledger.save_portfolio(portfolio, peak_equity=peak_equity)
    else:
        portfolio, peak_equity = loaded

    alpaca_connectivity = test_alpaca_paper()
    oanda_connectivity = test_oanda_practice()

    alpaca_positions = alpaca_open_positions() if alpaca_connectivity.ok else None
    oanda_positions = oanda_open_positions() if oanda_connectivity.ok else None

    broker_positions = []
    if alpaca_positions is not None:
        broker_positions.extend(
            normalize_alpaca_positions(alpaca_positions.details.get("positions", []))
        )
    if oanda_positions is not None:
        broker_positions.extend(
            normalize_oanda_positions(oanda_positions.details.get("positions", []))
        )

    reconciliation = PositionReconciler().reconcile(portfolio, broker_positions)
    profile = competitive_paper_profile()

    checks = {
        "alpaca_connectivity": alpaca_connectivity.ok,
        "oanda_connectivity": oanda_connectivity.ok,
        "broker_positions_readable": alpaca_positions is not None and oanda_positions is not None,
        "ledger_initialized": ledger.load_portfolio() is not None,
        "reconciliation_ok": reconciliation.ok,
        "idempotency_store_initialized": Path(args.idempotency).exists(),
        "live_trading_disabled_by_preflight": True,
    }
    ready = all(checks.values())

    output = {
        "ready_for_protected_practice_test": ready,
        "checks": checks,
        "reconciliation_reason": reconciliation.reason,
        "reconciliation_issues": [issue.__dict__ for issue in reconciliation.issues],
        "portfolio_equity": portfolio.equity,
        "peak_equity": peak_equity,
        "risk_profile": profile.name.value,
        "risk_per_trade_pct": profile.risk_limits.risk_per_trade_pct,
        "max_daily_loss_pct": profile.risk_limits.max_daily_loss_pct,
        "max_peak_drawdown_pct": profile.risk_limits.max_peak_drawdown_pct,
        "note": "Read-only preflight. This command never submits an order.",
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    if not ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
