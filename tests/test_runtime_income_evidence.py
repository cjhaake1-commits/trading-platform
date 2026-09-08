import json
import sqlite3
from datetime import UTC, datetime

from runtime_income_evidence import capital_diagnostics, cycle_evidence

NOW = datetime(2026, 9, 8, 23, tzinfo=UTC)


def test_absent_diagnostics_do_not_create_databases(tmp_path):
    result = capital_diagnostics(tmp_path, now=NOW)
    assert result["portfolio_state"] is None
    result = cycle_evidence(tmp_path, now=NOW)
    assert result["provider_order_receipts_count"] is None
    assert result["observed_receipts_count"] == 0
    assert not (tmp_path / "var").exists()


def test_engine_receipts_are_deduplicated_without_claiming_fills_or_profit(tmp_path):
    db = tmp_path / "var/autotrader/lifecycle.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE engine_cycles(cycle_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, provider_status TEXT, payload_json TEXT)")
        for n in (1, 2):
            con.execute("INSERT INTO engine_cycles VALUES(?,?,?,?,?)", (
                f"autonomous-paper-trading:2026-09-08T22:0{n}:00+00:00", NOW.isoformat(), NOW.isoformat(), "OK",
                json.dumps({"risk_rejections": None, "entries": [{"broker": "alpaca-paper", "symbol": "TEST", "broker_order_id": "fixture-order", "quantity": 1}]})))
    result = cycle_evidence(tmp_path, now=NOW)
    assert result["provider_order_receipts_count"] == 1
    assert result["receipts"][0]["fill_confirmed"] is None
    assert result["receipts"][0]["platform_owned"] is None
    assert result["net_realized_income"] is None
    limited = cycle_evidence(tmp_path, now=NOW, per_engine_limit=1)
    assert limited["window_complete"] is False
    assert limited["provider_order_receipts_count"] is None
