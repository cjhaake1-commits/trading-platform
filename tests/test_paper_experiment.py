from autotrader.models import AssetClass, Instrument, MarketBar, Side, TradeProposal
from autotrader.paper_experiment import (
    PaperExperimentConfig,
    PaperExperimentLedger,
    estimate_edge,
    experimental_candidate,
)
from autotrader.scanner import CandidateScanner


def _bars(count=25):
    return [
        MarketBar("BTC/USD", AssetClass.CRYPTO, __import__("datetime").datetime(2026, 1, 1 + i), 100 + i, 101 + i, 99 + i, 100 + i, 1000)
        for i in range(count)
    ]


def test_experiment_is_fail_closed_for_live_or_non_paper():
    assert not PaperExperimentConfig.from_env({"PAPER_EXPERIMENT_MODE": "true", "LIVE_TRADING_ENABLED": "true", "ALPACA_ENV": "paper"}).enabled
    assert not PaperExperimentConfig.from_env({"PAPER_EXPERIMENT_MODE": "true", "LIVE_TRADING_ENABLED": "false", "ALPACA_ENV": "live"}).enabled
    assert PaperExperimentConfig.from_env({"PAPER_EXPERIMENT_MODE": "true", "LIVE_TRADING_ENABLED": "false", "ALPACA_ENV": "paper", "ALPACA_PAPER_BASE_URL": "https://paper-api.alpaca.markets"}).enabled


def test_edge_is_cost_positive_and_explicitly_units_assumptions():
    bars = _bars()
    candidate = CandidateScanner().score_instrument(Instrument("BTC/USD", AssetClass.CRYPTO), bars)
    proposal = TradeProposal("BTC/USD", AssetClass.CRYPTO, Side.BUY, 124, 121.52, 0.6, "test")
    edge = estimate_edge(candidate, proposal, asset_class=AssetClass.CRYPTO, experimental=True)
    assert edge.expected_net_edge == edge.expected_gross_move - edge.spread_cost - edge.fee_cost - edge.slippage_cost
    assert edge.assumptions["cost_units"] == "decimal_return"
    assert edge.expected_net_edge > edge.required_edge


def test_mean_reversion_candidate_can_be_experimental_without_positive_momentum_veto():
    bars = []
    prices = [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 80, 79, 78, 77, 76, 75]
    for i, price in enumerate(prices):
        bars.append(MarketBar("BTC/USD", AssetClass.CRYPTO, __import__("datetime").datetime(2026, 1, 1 + i), price, price + 1, price - 1, price, 1000))
    instrument = Instrument("BTC/USD", AssetClass.CRYPTO)
    candidate = CandidateScanner().score_instrument(instrument, bars)
    proposal = TradeProposal("BTC/USD", AssetClass.CRYPTO, Side.BUY, 75, 73.5, 0.6, "mean_reversion")
    selected = experimental_candidate(candidate, (proposal,), config=PaperExperimentConfig(enabled=True))
    assert selected is not None


def test_champion_challenger_decision_and_outcome_are_persisted(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    decision_id = ledger.record_decision(
        pillar="alpaca_crypto", symbol="BTC/USD", strategy="mean_reversion", timeframe="15m",
        lane="EXPERIMENTAL_PAPER", decision="candidate", entry_price=100.0, edge=None, features={"score": 8.0},
    )
    ledger.record_outcome(decision_id, {"pnl": -1.0, "mfe": 2.0, "mae": -3.0})
    import sqlite3
    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        row = connection.execute("SELECT lane, outcome_json FROM experiment_decisions WHERE id=?", (decision_id,)).fetchone()
    assert row[0] == "EXPERIMENTAL_PAPER"
    assert "mfe" in row[1]
