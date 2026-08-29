from __future__ import annotations

from datetime import UTC, datetime

from autotrader.research_jobs import ResearchRefreshJob
from autotrader.research_platform import ResearchStore


def test_research_refresh_records_disabled_bloomberg_without_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOOMBERG_ENABLED", "false")
    monkeypatch.setenv("BENCHMARK_TRACKING_ENABLED", "false")
    path = tmp_path / "research.db"
    result = ResearchRefreshJob(path=str(path), benchmark_path=str(tmp_path / "benchmark.json")).run(
        datetime(2026, 8, 29, tzinfo=UTC)
    )
    assert result.ok is True
    assert result.data["bloomberg"]["state"] == "DISABLED"
    assert result.data["benchmark_market_data"]["state"] == "DISABLED"

    statuses = {row["lane"]: row for row in ResearchStore(path).provider_status()}
    assert statuses["bloomberg"]["status"] == "DISABLED"
    assert statuses["bloomberg"]["last_error"] is None


def test_missing_benchmark_snapshot_is_due_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BENCHMARK_TRACKING_ENABLED", raising=False)
    job = ResearchRefreshJob(
        path=str(tmp_path / "research.db"),
        benchmark_path=str(tmp_path / "benchmark.json"),
    )
    assert job._benchmark_due(datetime(2026, 8, 29, tzinfo=UTC)) is True


def test_benchmark_tracking_can_be_disabled_without_affecting_research(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TRACKING_ENABLED", "false")
    job = ResearchRefreshJob(
        path=str(tmp_path / "research.db"),
        benchmark_path=str(tmp_path / "benchmark.json"),
    )
    assert job._benchmark_due(datetime(2026, 8, 29, tzinfo=UTC)) is False
