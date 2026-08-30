import json
import sqlite3
from datetime import UTC, datetime

from scripts.create_overnight_error_ledger import build_error_ledger


def test_error_ledger_preserves_exception_and_unknown_repair_metadata(tmp_path):
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
        connection.execute(
            "INSERT INTO audit_events VALUES (1, 'runtime_job', 'Job raised an exception', ?, '2026-08-30T00:00:00+00:00')",
            (json.dumps({"job": "crypto", "ok": False, "error": "bad data", "exception_type": "ValueError"}),),
        )
        connection.execute(
            "INSERT INTO audit_events VALUES (2, 'runtime_job', 'no trade', ?, '2026-08-30T00:01:00+00:00')",
            (json.dumps({"job": "forex", "ok": True}),),
        )
    report = build_error_ledger(str(path), now=datetime(2026, 8, 30, 1, tzinfo=UTC))
    assert len(report["errors"]) == 1
    error = report["errors"][0]
    assert error["exception_type"] == "ValueError"
    assert error["root_cause"] == "bad data"
    assert error["repair"] == "UNKNOWN"
    assert report["safety"]["real_money_orders"] == 0
