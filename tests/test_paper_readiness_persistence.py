from autotrader.paper_readiness import build_readiness, persist_readiness


def test_readiness_snapshot_persists_all_pillars(tmp_path):
    snapshot = build_readiness(
        provider_status={"CRYPTO": {"connected": True, "market_data": True}},
        market_open={"CRYPTO": True},
    )
    assert persist_readiness(snapshot, tmp_path / "research.db") == 6
    import sqlite3
    with sqlite3.connect(tmp_path / "research.db") as connection:
        rows = connection.execute("SELECT pillar, status FROM paper_readiness_snapshots").fetchall()
    assert len(rows) == 6
    assert dict(rows)["CRYPTO"] == "READY"


def test_readiness_persistence_is_telemetry_only(tmp_path):
    snapshot = build_readiness()
    persist_readiness(snapshot, tmp_path / "research.db")
    assert snapshot["research_only"] is True
    assert snapshot["live_trading_enabled"] is False
