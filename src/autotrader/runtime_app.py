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
from .crypto_market_archive import AlpacaCryptoArchiveCollector
from .crypto_replay import load_archive
from .crypto_shadow import update_shadow
from .daily_learning import DailyLearningJob
from .fx_paper import FxPaperConfig, FxPaperTradingJob
from .high_velocity import micro_candidate, write_research_snapshot
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
                    return JobResult(
                        True,
                        "Active v2 reconciliation cooling down",
                        {"state": "RECONCILING", "retry_after_until": checkpoint.retry_after_until},
                    )
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
        return JobResult(
            True,
            "Active v2 reconciliation completed",
            {"state": state, "unresolved_before": result.unresolved_before,
             "unresolved_after": result.unresolved_after, **result.telemetry},
        )


@dataclass
class CryptoLifecycleReconciliationJob:
    ledger_path: str = "var/autotrader/portfolio.db"
    name: str = "crypto-lifecycle-reconciliation"
    cadence_seconds: float = 60.0

    def run(self, now: datetime) -> JobResult:
        result = reconcile_alpaca_equity_backlog(
            self.ledger_path,
            apply_paper_cleanup=True,
            scope="crypto",
            broker="alpaca-crypto-paper",
            budget_limit=12,
        )
        state = "RECONCILING" if result.unresolved_after else "CLEAR"
        return JobResult(
            True,
            "Crypto lifecycle reconciliation completed",
            {"state": state, "unresolved_before": result.unresolved_before,
             "unresolved_after": result.unresolved_after, **result.telemetry},
        )
@dataclass
class CryptoMarketDataArchiveJob:
    name: str = "crypto-market-data-archive"
    cadence_seconds: float = 900.0
    collector: AlpacaCryptoArchiveCollector = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.collector is None:
            self.collector = AlpacaCryptoArchiveCollector()

    def run(self, now: datetime) -> JobResult:
        try:
            result = self.collector.run_once(lookback_hours=24)
            return JobResult(True, "Crypto market-data archive refreshed", {"refreshed_at": now.isoformat(), **result})
        except Exception as exc:  # archive failure must not affect execution jobs
            return JobResult(
                True,
                "Crypto market-data archive unavailable",
                {"state": "PROVIDER_DEGRADED", "error": str(exc), "refreshed_at": now.isoformat()},
            )


@dataclass
class CryptoShadowValidationJob:
    name: str = "crypto-shadow-validation"
    cadence_seconds: float = 300.0

    def run(self, now: datetime) -> JobResult:
        result = update_shadow()
        return JobResult(
            True,
            "Crypto ADA candidate shadow validation updated",
            {
                "state": result["state"],
                "signals": result["signals"],
                "completed_shadow_trades": result["completed_shadow_trades"],
                "updated_at": now.isoformat(),
                "broker_submission": False,
            },
        )


@dataclass
class HighVelocityResearchJob:
    name: str = "high-velocity-research"
    cadence_seconds: float = 300.0

    def run(self, now: datetime) -> JobResult:
        archives = load_archive("var/autotrader/crypto_market_data.db", "5m", 60)
        candidates = []
        for symbol, bars in sorted(archives.items(), key=lambda item: len(item[1]), reverse=True)[:8]:
            move = bars[-1].close / bars[-2].close - 1
            candidate = micro_candidate(
                symbol=symbol,
                pillar="Crypto",
                direction="LONG" if move >= 0 else "SHORT",
                strategy="intraday_momentum",
                timeframe="5m",
                signal_strength=min(abs(move) * 100, 1.0),
                expected_gross_edge=abs(move),
                costs=0.002,
            )
            if candidate:
                candidates.append(candidate)
        snapshot = write_research_snapshot(candidates=candidates, derivative_rows=[], arbitrage_rows=[])
        return JobResult(
            True,
            "High-velocity paper research evaluated",
            {
                "candidates": len(candidates),
                "positive_net_edge": len(candidates),
                "paper_executions": 0,
                "derivative_simulations": 0,
                "arbitrage_observations": 0,
                "updated_at": snapshot["updated_at"],
            },
        )


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
        jobs.append(CryptoLifecycleReconciliationJob(ledger_path=args.ledger))
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
        jobs.append(CryptoMarketDataArchiveJob())
        jobs.append(CryptoShadowValidationJob())
        jobs.append(HighVelocityResearchJob())
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
