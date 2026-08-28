from __future__ import annotations

import argparse
import json
import os
import sqlite3
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
from .edge_engine import benchmark_metrics, classify_edge
from .fx_paper import FxPaperConfig, FxPaperTradingJob
from .high_velocity import micro_candidate, write_research_snapshot
from .lane_ledger import PaperLaneLedger
from .pillar_jobs import InternationalPaperTradingJob, MetalsPaperTradingJob
from .portfolio_ledger import PortfolioLedger
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
class FoundationAuditJob:
    """Persist truthful accounting/learning readiness without broker mutation."""
    ledger_path: str = "var/autotrader/portfolio.db"
    report_path: str = "var/autotrader/foundation-report.json"
    name: str = "foundation-audit"
    cadence_seconds: float = 120.0

    def run(self, now: datetime) -> JobResult:
        ledger = PortfolioLedger(self.ledger_path)
        pillars = ("Stocks", "Crypto", "Forex", "Metals/Commodities", "International", "Kalshi")
        key_map = {"Stocks": "alpaca_equities", "Crypto": "alpaca_crypto", "Forex": "oanda_fx",
                   "Metals/Commodities": "alpaca_metals", "International": "ibkr_global", "Kalshi": "kalshi"}
        day = now.astimezone(UTC).date().isoformat()
        for pillar in pillars:
            if not ledger.load_pillar_day_start_equity(pillar=key_map[pillar], equity_date=day):
                ledger.save_pillar_day_start_equity(
                    pillar=key_map[pillar], equity_date=day, timezone="UTC",
                    day_start_timestamp=f"{day}T00:00:00+00:00", starting_economic_equity=1000.0,
                    source="paper_allocation_cap_pending_provider_reconciliation",
                )
        with sqlite3.connect(self.ledger_path) as connection:
            fills = connection.execute("SELECT broker,symbol,side,quantity,price,realized_pnl,occurred_at,metadata_json FROM fills").fetchall()
        crypto = [row for row in fills if "crypto" in str(row[0]).lower()]
        snapshot_path = Path("dashboard/data.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.exists() else {}
        performance = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
        positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
        position_values = {pillar: 0.0 for pillar in pillars}
        for position in positions:
            if not isinstance(position, dict):
                continue
            raw = str(position.get("pillar") or "").lower()
            pillar = "Crypto" if "crypto" in raw else "Metals/Commodities" if "metal" in raw else "Stocks"
            position_values[pillar] += float(position.get("market_value") or 0.0)
        normalized = {}
        for pillar in pillars:
            values = performance.get(pillar) or {}
            realized = float(values.get("net_generated_cash") or 0.0)
            unrealized = float(values.get("unrealized_pnl") or 0.0)
            starting = float(values.get("starting_allocation") or 1000.0)
            economic = starting + realized + unrealized
            deployed = float(values.get("capital_deployed") or 0.0)
            available = float(values.get("available_cash") or 0.0)
            market_value = position_values[pillar]
            difference = economic - (available + market_value)
            status = "ACCOUNTING_VERIFIED" if abs(difference) <= 0.02 else "ACCOUNTING_UNVERIFIED"
            reason = "provider snapshot identity matched" if status == "ACCOUNTING_VERIFIED" else (
                f"available_cash + position_market_value differs by {difference:.6f}; "
                "source fields: available_cash, capital_deployed, unrealized_pnl"
            )
            record = {"pillar": pillar, "observed_at": now.isoformat(), "allocation_cap": 1000.0,
                      "starting_equity": starting, "economic_equity": economic, "available_cash": available,
                      "deployed_cash": deployed, "pending": 0.0, "notional_exposure": market_value,
                      "position_market_value": market_value, "realized_today": realized, "unrealized": unrealized,
                      "accounting_status": status, "identity_difference": difference, "reason": reason,
                      "source": "dashboard/data.json provider-backed snapshot", "freshness": "CURRENT_SNAPSHOT"}
            ledger.save_accounting_snapshot(record)
            normalized[pillar] = record
        outcomes = []  # Legacy fills have no explicit accounting verification and cannot affect learning.
        report = {
            "observed_at": now.isoformat(), "pillars": {p: {"accounting_status": normalized[p]["accounting_status"],
            "identity_difference": normalized[p]["identity_difference"], "reason": normalized[p]["reason"],
            "day_start_persisted": True} for p in pillars},
            "crypto": {"provider_fill_rows": len(crypto), "verified_outcomes": len(outcomes),
                       "benchmark": benchmark_metrics(outcomes, starting_equity=1000.0),
                       "edge_state": classify_edge(benchmark_metrics(outcomes, starting_equity=1000.0))},
            "learning_gate": "ACCOUNTING_VERIFIED_ONLY", "provider_mutation": False,
        }
        path = Path(self.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return JobResult(True, "Foundation audit persisted", {"report": self.report_path,
                         "crypto_provider_fill_rows": len(crypto), "verified_outcomes": 0})


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
        ledger = PaperLaneLedger()
        for candidate in candidates:
            ledger.record(
                timestamp=now.astimezone(UTC).isoformat(), pillar=candidate.pillar,
                lane="DAY_TRADE", strategy=candidate.strategy, symbol=candidate.symbol,
                direction=candidate.direction, provider="research-only", timeframe=candidate.timeframe,
                mode="PAPER_RESEARCH", candidate_score=candidate.signal_strength,
                confidence=candidate.confidence, gross_expected_edge=candidate.expected_gross_edge,
                estimated_costs=candidate.estimated_costs, net_expected_edge=candidate.expected_net_edge,
                capital_committed=0.0, notional_exposure=0.0, status="QUALIFIED",
            )
        for lane, reason in (
            ("SHORT", "CAPABILITY_BLOCKED: no confirmed short execution candidate in this cycle"),
            ("DERIVATIVE_SIM", "CAPABILITY_BLOCKED: no connected provider derivative capability/data"),
            ("ARBITRAGE_SIM", "CAPABILITY_BLOCKED: no authenticated executable quote source"),
        ):
            ledger.record(timestamp=now.astimezone(UTC).isoformat(), pillar="Research", lane=lane,
                          strategy="capability_discovery", symbol="", direction="", provider="provider-truth",
                          timeframe="", mode="PAPER_RESEARCH", exit_reason=reason, status="REJECTED")
        lane_summary = ledger.write_summary()
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
                "lane_ledger": "var/autotrader/learning/paper-lanes.db",
                "lane_summary": lane_summary,
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
    jobs = [HeartbeatJob(), FoundationAuditJob(ledger_path=args.ledger)]
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
