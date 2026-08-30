import sqlite3

from autotrader.paper_experiment import PaperExperimentLedger
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


def test_shadow_attribution_expands_new_contributing_strategies(tmp_path):
    db = tmp_path / "paper_experiment.db"
    ledger = PaperExperimentLedger(db)
    ledger.record_shadow_trade(
        shadow_id="S1", experiment_id="E1", pillar="Crypto", strategy_id="crypto.confluence.v1",
        market="BTC/USD", direction="BUY", hypothetical_entry=100, entry_at="2026-08-30T00:00:00+00:00",
        entry_reason="test", contributing_strategies=["crypto.momentum", "crypto.breakout"],
        strategy_version="v1", timeframe="15m", confidence=0.8, confluence_bucket="AGREEMENT_2",
    )
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE shadow_trades SET result='WIN', hypothetical_pnl=2, exit_at='2026-08-30T01:00:00+00:00'")
    report = build_report(str(db))
    assert report["by_dimension"]["strategy"]["crypto.momentum"]["completed"] == 1
    assert report["by_dimension"]["strategy_version"]["v1"]["completed"] == 1
    assert report["by_dimension"]["timeframe"]["15m"]["completed"] == 1
    assert report["by_dimension"]["confidence_bucket"][">=0.70"]["completed"] == 1
    assert report["by_dimension"]["confluence_bucket"]["AGREEMENT_2"]["completed"] == 1
