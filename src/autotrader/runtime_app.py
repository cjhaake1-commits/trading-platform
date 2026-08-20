from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .audit import SQLiteAuditStore
from .autonomous_paper import AutonomousPaperConfig, AutonomousPaperTradingJob
from .capital_allocations import TOTAL_PAPER_CAPITAL
from .daily_learning import DailyLearningJob
from .fx_paper import FxPaperConfig, FxPaperTradingJob
from .runtime import AutonomousRuntime, JobResult, RunMode, RuntimeConfig

AUTONOMOUS_ARM_ENV = "AUTONOMOUS_TRADING_ENABLED"


def autonomous_trading_armed() -> bool:
    """Require an exact local opt-in; missing or malformed values fail closed."""
    return os.getenv(AUTONOMOUS_ARM_ENV, "false").strip().lower() == "true"


@dataclass
class HeartbeatJob:
    name: str = "health"
    cadence_seconds: float = 30.0

    def run(self, now: datetime) -> JobResult:
        return JobResult(True, "Runtime health check passed", {"timestamp": now.isoformat()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous trading runtime supervisor")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode], default="paper")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    parser.add_argument("--status", default="var/autotrader/status.json")
    parser.add_argument("--heartbeat", type=float, default=1.0)
    parser.add_argument("--trade-cadence", type=float, default=300.0)
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--idempotency", default="var/autotrader/idempotency.db")
    parser.add_argument("--initial-equity", type=float, default=TOTAL_PAPER_CAPITAL)
    parser.add_argument(
        "--autonomous-paper",
        action="store_true",
        help="Enable autonomous Alpaca paper + OANDA practice scanning and protected execution",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    mode = RunMode(args.mode)
    if args.autonomous_paper and mode is not RunMode.PAPER:
        raise SystemExit("--autonomous-paper is only valid with --mode paper")

    autonomous_enabled = args.autonomous_paper and autonomous_trading_armed()
    config = RuntimeConfig(
        mode=mode,
        heartbeat_seconds=args.heartbeat,
        snapshot_path=Path(args.status),
        autonomous_enabled=autonomous_enabled,
    )
    jobs = [HeartbeatJob()]
    if args.autonomous_paper:
        jobs.append(
            AutonomousPaperTradingJob(
                AutonomousPaperConfig(
                    ledger_path=args.ledger,
                    idempotency_path=args.idempotency,
                    initial_equity=args.initial_equity,
                    cadence_seconds=args.trade_cadence,
                    oanda_universe=(),
                )
            )
        )
        jobs.append(
            FxPaperTradingJob(
                FxPaperConfig(
                    ledger_path=args.ledger,
                    idempotency_path=args.idempotency,
                    initial_equity=args.initial_equity,
                    cadence_seconds=args.trade_cadence,
                )
            )
        )
        jobs.append(DailyLearningJob(audit_db=args.audit_db))

    runtime = AutonomousRuntime(
        jobs=jobs,
        audit=SQLiteAuditStore(args.audit_db),
        config=config,
        now_factory=lambda: datetime.now(UTC),
    )
    if args.autonomous_paper and not autonomous_enabled:
        runtime.disable_job(
            "autonomous-paper-trading",
            f"Execution disarmed: {AUTONOMOUS_ARM_ENV} must be explicitly true",
        )
        runtime.disable_job(
            "oanda-fx-paper-trading",
            f"Execution disarmed: {AUTONOMOUS_ARM_ENV} must be explicitly true",
        )
    runtime.run_forever()


if __name__ == "__main__":
    main()
