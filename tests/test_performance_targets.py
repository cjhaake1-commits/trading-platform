from autotrader.performance_targets import DailyPerformanceSnapshot, StretchGoalTracker


def test_tracks_stretch_thresholds_without_quota_sizing():
    tracker = StretchGoalTracker()
    status = tracker.status(
        DailyPerformanceSnapshot(
            start_equity=1000.0,
            current_equity=1250.0,
            realized_pnl=200.0,
            unrealized_pnl=50.0,
        )
    )
    assert status["hit_10_pct"]
    assert status["hit_20_pct"]
    assert not status["hit_30_pct"]
    assert status["quota_driven_sizing_allowed"] is False
