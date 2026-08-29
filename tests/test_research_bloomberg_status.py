from __future__ import annotations

from datetime import UTC, datetime

from autotrader.research_jobs import ResearchRefreshJob
from autotrader.research_platform import ResearchStore


def test_research_refresh_records_disabled_bloomberg_without_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOOMBERG_ENABLED", "false")
    path = tmp_path / "research.db"
    result = ResearchRefreshJob(path=str(path)).run(datetime(2026, 8, 29, tzinfo=UTC))
    assert result.ok is True
    assert result.data["bloomberg"]["state"] == "DISABLED"

    statuses = {row["lane"]: row for row in ResearchStore(path).provider_status()}
    assert statuses["bloomberg"]["status"] == "DISABLED"
    assert statuses["bloomberg"]["last_error"] is None
