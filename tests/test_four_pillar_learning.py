import json
import sqlite3

from autotrader.brokers.ibkr_global import IBKRGlobalPaperAdapter
from autotrader.capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL
from autotrader.learning import (
    BASELINE_MODEL_VERSION,
    DEFAULT_PARAMETERS,
    RealizedOutcomeLearner,
    learning_score,
    load_learned_parameters,
)


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
                "pillar_allocations": {"alpaca_crypto": 999999},
                "autonomous_trading_enabled": True,
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


def _records(values, *, pillar="Crypto", regime="trend", costs=0.0):
    return [
        {
            "broker": "alpaca-paper",
            "symbol": "BTC/USD",
            "pillar": pillar,
            "market_regime": regime,
            "realized_pnl": value,
            "fees_costs": costs,
        }
        for value in values
    ]


def test_learning_score_excludes_unrealized_and_subtracts_costs():
    result = learning_score(
        [
            {"realized_pnl": 10.0, "fees_costs": 2.0, "unrealized_pnl": 9999.0},
            {"unrealized_pnl": 5000.0},
        ]
    )
    assert result["net_realized_cash"] == 8.0
    assert result["trading_costs"] == 2.0
    assert result["completed_trades"] == 1.0


def test_challenger_cannot_modify_hard_controls(tmp_path):
    learner = RealizedOutcomeLearner(model_state_path=str(tmp_path / "state.json"))
    proposed = learner.propose_challenger(
        {**DEFAULT_PARAMETERS, "risk_per_trade_pct": 0.99, "pillar_allocations": 999999},
        sample_size=20,
    )
    assert "risk_per_trade_pct" not in proposed
    assert "pillar_allocations" not in proposed
    assert proposed["minimum_candidate_score"] != 0.99


def test_insufficient_sample_and_oos_underperformance_block_promotion(tmp_path):
    learner = RealizedOutcomeLearner(model_state_path=str(tmp_path / "state.json"))
    blocked = learner.evaluate_challenger(_records([1.0] * 20), _records([1.0] * 2))
    assert blocked["promoted"] is False
    underperforming = learner.evaluate_challenger(_records([1.0] * 20), _records([-1.0] * 20))
    assert underperforming["sample_ok"] is True
    assert underperforming["promoted"] is False


def test_drawdown_and_parameter_change_guardrails_block_promotion(tmp_path):
    learner = RealizedOutcomeLearner(model_state_path=str(tmp_path / "state.json"))
    baseline = _records([1.0] * 20)
    challenger = _records([2.0] * 19 + [-100.0])
    evaluation = learner.evaluate_challenger(
        baseline,
        challenger,
        challenger_parameters={**DEFAULT_PARAMETERS, "strategy_weight": 1.5},
    )
    assert evaluation["drawdown_ok"] is False
    assert evaluation["parameter_change_ok"] is False
    assert evaluation["promoted"] is False


def test_successful_promotion_cooldown_and_rollback(tmp_path):
    state_path = tmp_path / "state.json"
    learner = RealizedOutcomeLearner(model_state_path=str(state_path))
    baseline = _records([0.5] * 20)
    challenger = _records([2.0] * 20)
    evaluation = learner.evaluate_challenger(baseline, challenger)
    assert evaluation["promoted"] is True
    version = learner.promote_challenger(evaluation, learner.propose_challenger(DEFAULT_PARAMETERS, sample_size=20))
    assert version != BASELINE_MODEL_VERSION
    cooldown = learner.evaluate_challenger(baseline, challenger)
    assert cooldown["cooldown_ok"] is False
    assert learner.rollback_if_underperforming(_records([-2.0] * 20), prior_score=10.0) is True
    assert json.loads(state_path.read_text())["active_version"] == BASELINE_MODEL_VERSION


def test_regime_and_pillar_scores_are_independent(tmp_path):
    learner = RealizedOutcomeLearner(model_state_path=str(tmp_path / "state.json"))
    records = _records([2.0], pillar="Crypto", regime="trend") + _records(
        [-1.0], pillar="Forex", regime="range"
    )
    assert learner.regime_scores(records)["trend"]["net_realized_cash"] == 2.0
    assert learner.pillar_scores(records)["Forex"]["net_realized_cash"] == -1.0


def test_cash_no_trade_beats_weak_trade():
    assert learning_score([])["score"] == 0.0
    assert learning_score(_records([-1.0]))["score"] < learning_score([])["score"]
