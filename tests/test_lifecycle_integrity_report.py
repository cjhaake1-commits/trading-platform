import json
import sqlite3

from scripts.create_lifecycle_integrity_report import build_report


def test_integrity_report_distinguishes_null_from_duplicate_event_ids(tmp_path):
    db = tmp_path / "paper_experiment.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE activity_observations (event_id TEXT, experiment_id TEXT)")
        connection.executemany("INSERT INTO activity_observations VALUES (?, ?)", [(None, "E1"), ("A", "E1"), ("B", "E1")])
        connection.execute("""CREATE TABLE shadow_trades (
            experiment_id TEXT, direction TEXT
        )""")
        connection.execute("INSERT INTO shadow_trades VALUES ('E1', 'BUY')")
    report = build_report(str(db), str(tmp_path / "report.json"))
    assert report["activity"]["null_event_ids"] == 1
    assert report["activity"]["duplicate_event_ids"] == 0
    assert report["invariants"]["distinct_event_identity"] is False
    assert json.loads((tmp_path / "report.json").read_text())["shadow"]["missing_parent"] == 0
