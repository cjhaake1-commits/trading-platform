import json
import sqlite3

from scripts.repair_edge_semantics import repair


def test_repair_moves_legacy_economics_to_explicit_proxies(tmp_path):
    db = tmp_path / "experiment.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE activity_observations (event_id TEXT PRIMARY KEY, strategy TEXT, estimated_edge REAL, expected_value REAL, features_json TEXT)")
        connection.execute("INSERT INTO activity_observations VALUES ('e1', 'crypto.momentum', .2, .1, ?)", (json.dumps({"source_method": "sma_cross"}),))
        connection.execute("INSERT INTO activity_observations VALUES ('e2', 'sma_cross', .3, .2, ?)", (json.dumps({"source_method": "legacy"}),))
    assert repair(str(db)) == 1
    with sqlite3.connect(db) as connection:
        calibrated = connection.execute("SELECT estimated_edge,expected_value FROM activity_observations WHERE event_id='e1'").fetchone()
        features = json.loads(connection.execute("SELECT features_json FROM activity_observations WHERE event_id='e1'").fetchone()[0])
        untouched = connection.execute("SELECT estimated_edge FROM activity_observations WHERE event_id='e2'").fetchone()[0]
    assert calibrated == (None, None)
    assert features["edge_proxy"] == .2 and features["edge_semantics"] == "EDGE_PROXY"
    assert untouched == .3


def test_repair_is_idempotent(tmp_path):
    db = tmp_path / "experiment.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE activity_observations (event_id TEXT PRIMARY KEY, strategy TEXT, estimated_edge REAL, expected_value REAL, features_json TEXT)")
        connection.execute("INSERT INTO activity_observations VALUES ('e1', 'crypto.breakout', .2, .1, ?)", (json.dumps({"source_method": "breakout"}),))
    assert repair(str(db)) == 1
    assert repair(str(db)) == 0
