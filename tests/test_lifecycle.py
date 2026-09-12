from datetime import UTC, datetime, timedelta

from autotrader.lifecycle import classify_cycle


def test_closed_market_is_not_stall():
    p = classify_cycle({"stage": "CANDIDATES", "stop_reason": "MARKET_CLOSED"})
    assert p["state"] == "MARKET_CLOSED"


def test_old_progress_is_stall():
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert classify_cycle({"stage": "MARKET_DATA", "finished_at": old})["state"] == "PIPELINE_STALL"
