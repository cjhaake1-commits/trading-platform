from __future__ import annotations

import json
from datetime import UTC, datetime

from autotrader.benchmark_readiness import BenchmarkDefinition
from autotrader.benchmark_tracking import (
    BenchmarkTracker,
    PriceObservation,
    maximum_drawdown,
    summarize_benchmark,
)
from autotrader.research_jobs import BenchmarkTrackingJob


BENCHMARK = BenchmarkDefinition(
    key="test",
    label="Test Benchmark",
    category="index",
    public_symbol="TEST",
    bloomberg_security="TEST Index",
    purpose="unit test",
)


class FakeProvider:
    source_name = "fake-provider"

    def history(self, symbol: str, *, period: str = "1y", interval: str = "1d"):
        assert symbol == "TEST"
        assert period == "1y"
        assert interval == "1d"
        return tuple(
            PriceObservation(timestamp=f"2026-01-{index + 1:02d}T00:00:00+00:00", adjusted_close=100 + index)
            for index in range(30)
        )


class FailingProvider:
    source_name = "failing-provider"

    def history(self, symbol: str, *, period: str = "1y", interval: str = "1d"):
        raise RuntimeError("provider offline")


def test_maximum_drawdown_uses_positive_price_path():
    assert maximum_drawdown([100, 120, 90, 110]) == 0.25
    assert maximum_drawdown([]) is None


def test_summary_exposes_time_matched_returns_and_drawdown():
    metrics = summarize_benchmark(BENCHMARK, FakeProvider().history("TEST"), source="fake-provider")
    assert metrics.state == "READY"
    assert metrics.observations == 30
    assert metrics.returns["1d"] == 129 / 128 - 1
    assert metrics.returns["21d"] == 129 / 108 - 1
    assert metrics.maximum_drawdown == 0.0


def test_tracker_collects_coverage_without_broker_control():
    snapshot = BenchmarkTracker(FakeProvider(), benchmarks=(BENCHMARK,)).collect()
    assert snapshot["ready_count"] == 1
    assert snapshot["coverage"] == 1.0
    assert snapshot["broker_control"] is False
    assert snapshot["benchmarks"]["test"]["source"] == "fake-provider"


def test_tracking_job_writes_snapshot_and_provider_status(tmp_path):
    snapshot_path = tmp_path / "benchmark.json"
    research_path = tmp_path / "research.db"
    job = BenchmarkTrackingJob(
        path=str(snapshot_path),
        research_path=str(research_path),
        tracker=BenchmarkTracker(FakeProvider(), benchmarks=(BENCHMARK,)),
    )
    result = job.run(datetime(2026, 8, 29, tzinfo=UTC))
    assert result.ok is True
    assert result.data["state"] == "CONNECTED"
    payload = json.loads(snapshot_path.read_text())
    assert payload["ready_count"] == 1


def test_provider_failure_is_recorded_without_crashing_runtime(tmp_path):
    job = BenchmarkTrackingJob(
        path=str(tmp_path / "benchmark.json"),
        research_path=str(tmp_path / "research.db"),
        tracker=BenchmarkTracker(FailingProvider(), benchmarks=(BENCHMARK,)),
    )
    result = job.run(datetime(2026, 8, 29, tzinfo=UTC))
    assert result.ok is True
    assert result.data["state"] == "UNAVAILABLE"
    assert result.data["ready"] == 0
