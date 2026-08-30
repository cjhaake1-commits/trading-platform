import sqlite3

from scripts.create_shadow_attribution_report import build_report


def test_shadow_attribution_isolated_to_completed_crypto_rows(tmp_path):
    db = tmp_path / "paper_experiment.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE shadow_trades (pillar TEXT, strategy_id TEXT, market TEXT, direction TEXT, qualification_score REAL, regime TEXT, exit_reason TEXT, hypothetical_pnl REAL, result TEXT)")
        connection.executemany("INSERT INTO shadow_trades VALUES (?,?,?,?,?,?,?,?,?)", [
            ("Crypto", "MOMENTUM", "BTC/USD", "BUY", 72, "TRENDING", "TARGET", 2.0, "WIN"),
            ("Crypto", "MOMENTUM", "BTC/USD", "BUY", 72, "TRENDING", "STOP", -3.0, "LOSS"),
            ("Stocks", "MOMENTUM", "AAPL", "BUY", 90, "TRENDING", "TARGET", 99.0, "WIN"),
            ("Crypto", "BREAKOUT", "ETH/USD", "SELL", 80, "RANGE", "TIME_STOP", 0.0, None),
        ])
    report = build_report(str(db))
    assert report["overall"]["completed"] == 2
    assert report["overall"]["hypothetical_pnl"] == -1.0
    assert report["by_dimension"]["strategy"]["MOMENTUM"]["completed"] == 2
    assert report["by_dimension"]["timeframe"]["UNKNOWN"]["completed"] == 2
    assert report["negative_expectancy_shape"] == "INSUFFICIENT_EVIDENCE"
