from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_reconciler():
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from autotrader.alpaca_backlog import reconcile_alpaca_equity_backlog

    return reconcile_alpaca_equity_backlog


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile unresolved Alpaca PAPER equity entry manifests")
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--status", default="var/autotrader/status.json")
    parser.add_argument("--apply-paper-cleanup", action="store_true")
    parser.add_argument("--active-v2", action="store_true", help="Reconcile active five_pillar_paper_v2 manifests")
    parser.add_argument("--budget-limit", type=int, default=12)
    args = parser.parse_args()

    status_path = Path(args.status)
    status = {}
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            status = {}
    if bool(status.get("live_trading_enabled")):
        raise SystemExit("LIVE_TRADING_ENABLED must remain false")

    reconcile_alpaca_equity_backlog = _load_reconciler()
    result = reconcile_alpaca_equity_backlog(
        args.ledger,
        apply_paper_cleanup=args.apply_paper_cleanup,
        scope="active_v2" if args.active_v2 else "legacy",
        checkpoint_path=(
            "var/autotrader/alpaca_active_v2_checkpoint.json"
            if args.active_v2
            else None
        ),
        budget_limit=args.budget_limit,
    )
    print(
        json.dumps(
            {
                "dry_run": result.dry_run,
                "unresolved_before": result.unresolved_before,
                "unresolved_after": result.unresolved_after,
                "duplicate_orders_cancelled": list(result.duplicate_orders_cancelled),
                "telemetry": result.telemetry,
                "classifications": [classification.__dict__ for classification in result.classifications],
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
