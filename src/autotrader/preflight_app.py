from __future__ import annotations

import argparse
import json

from .preflight import run_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only broker and safety preflight")
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--idempotency", default="var/autotrader/idempotency.db")
    parser.add_argument("--initial-equity", type=float, default=2000.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = run_preflight(
        ledger_path=args.ledger,
        idempotency_path=args.idempotency,
        initial_equity=args.initial_equity,
    )

    output = {
        "ready_for_protected_practice_test": report.ready,
        "checks": report.checks,
        "failed_checks": list(report.failed_checks),
        "messages": list(report.messages),
        "reconciliation_reason": report.reconciliation.reason,
        "reconciliation_issues": [issue.__dict__ for issue in report.reconciliation.issues],
        "portfolio_equity": report.portfolio.equity,
        "peak_equity": report.peak_equity,
        "risk_profile": report.profile.name.value,
        "risk_per_trade_pct": report.profile.risk_limits.risk_per_trade_pct,
        "max_daily_loss_pct": report.profile.risk_limits.max_daily_loss_pct,
        "max_peak_drawdown_pct": report.profile.risk_limits.max_peak_drawdown_pct,
        "note": "Read-only preflight. This command never submits an order.",
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    if not report.ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
