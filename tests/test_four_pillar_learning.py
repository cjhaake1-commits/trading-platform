import json
import sqlite3

from autotrader.brokers.ibkr_global import IBKRGlobalPaperAdapter
from autotrader.capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL
from autotrader.learning import DEFAULT_PARAMETERS, RealizedOutcomeLearner, load_learned_parameters


def test_five_pillar_capital_is_5000():
    assert TOTAL_PAPER_CAPITAL == 5000.0
    assert set(PILLAR_ALLOCATIONS) == {
        "alpaca_equities",
        "oanda_fx",
        "alpaca_crypto",
        "alpaca_metals",
        "ibkr_global",
    }
    assert all(value == 1000.0 for value in PILLAR_ALLOCATIONS.values())


def test_ibkr_pending_setup_is_fail_closed(monkeypatch):
    for name in ("IBKR_PAPER_ENABLED", "IBKR_PAPER_HOST", "IBKR_PAPER_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    status = IBKRGlobalPaperAdapter().status()
    assert status.connection_status == "PENDING_SETUP"
    assert not status.trading_enabled
    assert not status.scanning_enabled
    assert IBKRGlobalPaperAdapter().open_positions() == []


def test_corrupt_or_forbidden_learning_cannot_mutate_guardrails(tmp_path):
    path = tmp_path / "learned.json"
    path.write_text(
        json.dumps(
            {
                "risk_per_trade_pct": 0.99,
                "max_portfolio_risk_pct": 0.99,
                "max_peak_drawdown_pct": 0.99,
                "cash_reserve_pct": 0.0,
                "emergency_kill_switch": False,
                "broker_environment": "live",
                "minimum_candidate_score": 999,
            }
        ),
        encoding="utf-8",
    )
    assert load_learned_parameters(path) == DEFAULT_PARAMETERS
    path.write_text("not json", encoding="utf-8")
    assert load_learned_parameters(path) == DEFAULT_PARAMETERS


def test_learning_waits_for_minimum_samples(tmp_path):
    db = tmp_path / "portfolio.db"
    with sqlite3.connect(db) as con:
        con.execute(
            """
            CREATE TABLE fills (
                broker TEXT, symbol TEXT, side TEXT, quantity REAL, price REAL,
                realized_pnl REAL, occurred_at TEXT, metadata_json TEXT
            )
            """
        )
        for i in range(19):
            con.execute(
                "INSERT INTO fills VALUES ('paper','SPY','sell',1,100,1,?, '{}')", (f"2026-08-17T00:{i:02d}:00+00:00",)
            )
    learner = RealizedOutcomeLearner(
        ledger_path=str(db),
        stats_path=str(tmp_path / "stats.json"),
        parameters_path=str(tmp_path / "params.json"),
        history_path=str(tmp_path / "history.jsonl"),
    )
    result = learner.update()
    assert result["sample_status"] == "collecting_evidence"
    assert result["changes"] == []
    assert result["hard_guardrails_mutable"] is False
