from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .adapters.bloomberg import BloombergAdapter
from .benchmark_tracking import BenchmarkTracker, write_benchmark_snapshot
from .research_platform import ResearchStore, build_daily_report
from .runtime import JobResult


@dataclass
class ResearchRefreshJob:
    path: str = "var/autotrader/research.db"
    name: str = "research-refresh"
    cadence_seconds: float = 3600.0
    benchmark_path: str = "var/autotrader/benchmark-market-snapshot.json"
    benchmark_cadence_seconds: float = 21600.0

    def _benchmark_due(self, now: datetime) -> bool:
        if os.getenv("BENCHMARK_TRACKING_ENABLED", "true").strip().lower() != "true":
            return False
        snapshot = Path(self.benchmark_path)
        if not snapshot.exists():
            return True
        observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        age = observed.timestamp() - snapshot.stat().st_mtime
        return age >= self.benchmark_cadence_seconds

    def run(self, now: datetime) -> JobResult:
        store = ResearchStore(self.path)
        counts = {
            lane: len(store.research(lane))
            for lane in ("etf", "institutional", "politician", "academic", "github")
        }
        for lane, count in counts.items():
            store.put_provider_status(
                lane,
                status="CONNECTED" if count else "UNAVAILABLE",
                records_ingested=count,
                last_error=None if count else "No records ingested",
            )

        bloomberg = BloombergAdapter().probe()
        store.put_provider_status(
            "bloomberg",
            status=bloomberg.state,
            records_ingested=0,
            last_error=None if bloomberg.connected or bloomberg.state == "DISABLED" else bloomberg.reason,
        )

        benchmark: dict[str, object] = {
            "state": "CACHED",
            "snapshot": self.benchmark_path,
            "research_only": True,
            "broker_control": False,
        }
        if self._benchmark_due(now):
            benchmark = BenchmarkTrackingJob(
                path=self.benchmark_path,
                research_path=self.path,
            ).run(now).data
        elif os.getenv("BENCHMARK_TRACKING_ENABLED", "true").strip().lower() != "true":
            benchmark["state"] = "DISABLED"

        return JobResult(
            True,
            "Research refresh completed",
            {
                "lanes": counts,
                "bloomberg": bloomberg.as_dict(),
                "benchmark_market_data": benchmark,
                "refreshed_at": now.isoformat(),
                "broker_control": False,
            },
        )


@dataclass
class BenchmarkTrackingJob:
    path: str = "var/autotrader/benchmark-market-snapshot.json"
    research_path: str = "var/autotrader/research.db"
    name: str = "benchmark-market-tracking"
    cadence_seconds: float = 21600.0
    tracker: BenchmarkTracker | None = None

    def run(self, now: datetime) -> JobResult:
        store = ResearchStore(self.research_path)
        try:
            snapshot = (self.tracker or BenchmarkTracker()).collect(period="1y", interval="1d")
            write_benchmark_snapshot(snapshot, self.path)
            ready = int(snapshot.get("ready_count") or 0)
            total = int(snapshot.get("benchmark_count") or 0)
            coverage = float(snapshot.get("coverage") or 0.0)
            state = "CONNECTED" if ready > 0 else "UNAVAILABLE"
            error = None if state == "CONNECTED" else "No benchmark histories were available"
            store.put_provider_status(
                "benchmark_market_data",
                status=state,
                records_ingested=ready,
                last_error=error,
            )
            return JobResult(
                True,
                "Benchmark market tracking refreshed",
                {
                    "state": state,
                    "ready": ready,
                    "total": total,
                    "coverage": coverage,
                    "source": snapshot.get("source"),
                    "snapshot": self.path,
                    "refreshed_at": now.isoformat(),
                    "research_only": True,
                    "broker_control": False,
                },
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            store.put_provider_status(
                "benchmark_market_data",
                status="UNAVAILABLE",
                records_ingested=0,
                last_error=reason,
            )
            return JobResult(
                True,
                "Benchmark market tracking unavailable",
                {
                    "state": "PROVIDER_DEGRADED",
                    "error": reason,
                    "snapshot": self.path,
                    "refreshed_at": now.isoformat(),
                    "research_only": True,
                    "broker_control": False,
                },
            )


@dataclass
class DailyReportJob:
    path: str = "var/autotrader/research.db"
    name: str = "daily-report"
    cadence_seconds: float = 86400.0

    def run(self, now: datetime) -> JobResult:
        store = ResearchStore(self.path)
        report = build_daily_report(
            report_date=now.date().isoformat(),
            starting_equity=5000.0,
            ending_equity=5000.0,
            realized_cash=0.0,
            liquid_cash=5000.0,
            redeployable_cash=5000.0,
            harvested_cash=0.0,
            unrealized_pnl=0.0,
            trades=0,
            wins=0,
            expectancy=0.0,
            profit_factor=None,
            drawdown=0.0,
            capital_utilization=0.0,
        )
        store.put_report(now.date(), report)
        return JobResult(True, "Daily report written", {"report_date": now.date().isoformat()})
