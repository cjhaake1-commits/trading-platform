from autotrader.backtest import compute_metrics


def test_metrics_compute_return_and_drawdown():
    metrics = compute_metrics([1000.0, 1050.0, 1020.0, 1100.0])
    assert round(metrics.cumulative_return_pct, 6) == 10.0
    assert metrics.maximum_drawdown_pct > 0
    assert metrics.sharpe_ratio is not None
    assert metrics.observations == 4


def test_metrics_reject_nonpositive_equity():
    try:
        compute_metrics([1000.0, 0.0])
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")
