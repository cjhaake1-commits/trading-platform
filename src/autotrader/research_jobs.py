from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .research_platform import ResearchStore, build_daily_report
from .runtime import JobResult


@dataclass
class ResearchRefreshJob:
    path: str = "var/autotrader/research.db"
    name: str = "research-refresh"
    cadence_seconds: float = 3600.0

    def run(self, now: datetime) -> JobResult:
        store = ResearchStore(self.path)
        counts = {lane: len(store.research(lane)) for lane in ("etf", "institutional", "politician", "academic", "github")}
        return JobResult(True, "Research refresh completed", {"lanes": counts, "refreshed_at": now.isoformat(), "broker_control": False})


@dataclass
class DailyReportJob:
    path: str = "var/autotrader/research.db"
    name: str = "daily-report"
    cadence_seconds: float = 86400.0

    def run(self, now: datetime) -> JobResult:
        store = ResearchStore(self.path)
        report = build_daily_report(report_date=now.date().isoformat(), starting_equity=5000.0, ending_equity=5000.0, realized_cash=0.0, liquid_cash=5000.0, redeployable_cash=5000.0, harvested_cash=0.0, unrealized_pnl=0.0, trades=0, wins=0, expectancy=0.0, profit_factor=None, drawdown=0.0, capital_utilization=0.0)
        store.put_report(now.date(), report)
        return JobResult(True, "Daily report written", {"report_date": now.date().isoformat()})
