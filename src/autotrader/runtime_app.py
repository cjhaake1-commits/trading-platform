from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .alpaca_backlog import load_backlog_checkpoint, reconcile_alpaca_equity_backlog
from .audit import SQLiteAuditStore
from .autonomous_paper import AutonomousPaperConfig, AutonomousPaperTradingJob
from .capital_allocations import TOTAL_PAPER_CAPITAL
from .daily_learning import DailyLearningJob
from .fx_paper import FxPaperConfig, FxPaperTradingJob
from .pillar_jobs import InternationalPaperTradingJob, MetalsPaperTradingJob
from .research_jobs import DailyReportJob, ResearchRefreshJob
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


@dataclass
class ActiveV2ReconciliationJob:
    ledger_path: str = "var/autotrader/portfolio.db"
    checkpoint_path: str = "var/autotrader/alpaca_active_v2_checkpoint.json"
    name: str = "active-v2-reconciliation"
    cadence_seconds: float = 120.0

    def run(self, now: datetime) -> JobResult:
        checkpoint = load_backlog_checkpoint(self.checkpoint_path)
        if checkpoint.retry_after_until:
            try:
                retry_at = datetime.fromisoformat(checkpoint.retry_after_until.replace("Z", "+00:00"))
                if retry_at > now.astimezone(UTC):
                    return JobResult(True, "Active v2 reconciliation cooling down", {"state": "RECONCILING", "retry_after_until": checkpoint.retry_after_until})
            except ValueError:
                pass
        result = reconcile_alpaca_equity_backlog(
            self.ledger_path,
            apply_paper_cleanup=True,
            scope="active_v2",
            checkpoint_path=self.checkpoint_path,
            budget_limit=12,
        )
        state = "RECONCILING" if result.unresolved_after else "CLEAR"
        return JobResult(True, "Active v2 reconciliation completed", {"state": state, "unresolved_before": result.unresolved_before, "unresolved_after": result.unresolved_after, **result.telemetry})


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
        jobs.append(ActiveV2ReconciliationJob(ledger_path=args.ledger))
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
        jobs.append(MetalsPaperTradingJob())
        jobs.append(InternationalPaperTradingJob())
        jobs.append(DailyLearningJob(audit_db=args.audit_db))
        jobs.append(ResearchRefreshJob())
        jobs.append(DailyReportJob())

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
        runtime.disable_job(
            "alpaca-metals-paper-trading",
            f"Execution disarmed: {AUTONOMOUS_ARM_ENV} must be explicitly true",
        )
        runtime.disable_job(
            "saxo-international-paper-trading",
            f"Execution disarmed: {AUTONOMOUS_ARM_ENV} must be explicitly true",
        )
    runtime.run_forever()


if __name__ == "__main__":
    main()
