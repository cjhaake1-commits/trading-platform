import sqlite3

from scripts.create_overnight_progress import build_progress


def test_progress_checkpoint_is_paper_only_and_preserves_unknowns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/autotrader").mkdir(parents=True)
    with sqlite3.connect(tmp_path / "var/autotrader/paper_experiment.db") as connection:
        connection.execute("CREATE TABLE activity_observations (experiment_id TEXT, event_id TEXT)")
        connection.execute("CREATE TABLE shadow_trades (exit_at TEXT, direction TEXT)")
        connection.execute("INSERT INTO activity_observations VALUES ('E1','V1')")
        connection.execute("INSERT INTO shadow_trades VALUES (NULL,'BUY')")
    report = build_progress()
    assert report["safety"]["live_trading_enabled"] is False
    assert report["safety"]["real_money_orders"] == 0
    assert report["activity"]["events"] == 1
    assert report["shadow"]["invalid_directions"] == 0
    assert report["runtime"]["healthy"] == "UNKNOWN"
