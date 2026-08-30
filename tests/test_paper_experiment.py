from autotrader.models import AssetClass, Instrument, MarketBar, Side, TradeProposal
from autotrader.paper_experiment import (
    PaperExperimentConfig,
    PaperExperimentLedger,
    estimate_edge,
    experimental_candidate,
    experimental_position_quantity_cap,
)
from autotrader.scanner import CandidateScanner


def _bars(count=25):
    return [
        MarketBar(
            "BTC/USD",
            AssetClass.CRYPTO,
            __import__("datetime").datetime(2026, 1, 1 + i),
            100 + i,
            101 + i,
            99 + i,
            100 + i,
            1000,
        )
        for i in range(count)
    ]


def test_experiment_is_fail_closed_for_live_or_non_paper():
    assert not PaperExperimentConfig.from_env(
        {"PAPER_EXPERIMENT_MODE": "true", "LIVE_TRADING_ENABLED": "true", "ALPACA_ENV": "paper"}
    ).enabled
    assert not PaperExperimentConfig.from_env(
        {"PAPER_EXPERIMENT_MODE": "true", "LIVE_TRADING_ENABLED": "false", "ALPACA_ENV": "live"}
    ).enabled
    assert PaperExperimentConfig.from_env(
        {
            "PAPER_EXPERIMENT_MODE": "true",
            "LIVE_TRADING_ENABLED": "false",
            "ALPACA_ENV": "paper",
            "ALPACA_PAPER_BASE_URL": "https://paper-api.alpaca.markets",
        }
    ).enabled


def test_high_velocity_research_flags_are_explicit_and_fail_closed():
    safe = {
        "PAPER_EXPERIMENT_MODE": "true",
        "MICRO_TRADING_EXPERIMENT_MODE": "true",
        "SHORT_EXPERIMENT_MODE": "true",
        "DERIVATIVES_RESEARCH_MODE": "true",
        "ARBITRAGE_RESEARCH_MODE": "true",
        "LIVE_TRADING_ENABLED": "false",
        "ALPACA_ENV": "paper",
        "ALPACA_PAPER_BASE_URL": "https://paper-api.alpaca.markets",
    }
    config = PaperExperimentConfig.from_env(safe)
    assert (
        config.enabled
        and config.micro_trading
        and config.short_experiment
        and config.derivatives_research
        and config.arbitrage_research
    )
    unsafe = dict(safe, LIVE_TRADING_ENABLED="true")
    blocked = PaperExperimentConfig.from_env(unsafe)
    assert not blocked.enabled and not blocked.micro_trading and not blocked.short_experiment


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
    prices = [
        110,
        109,
        108,
        107,
        106,
        105,
        104,
        103,
        102,
        101,
        100,
        99,
        98,
        97,
        96,
        95,
        94,
        93,
        92,
        80,
        79,
        78,
        77,
        76,
        75,
    ]
    for i, price in enumerate(prices):
        bars.append(
            MarketBar(
                "BTC/USD",
                AssetClass.CRYPTO,
                __import__("datetime").datetime(2026, 1, 1 + i),
                price,
                price + 1,
                price - 1,
                price,
                1000,
            )
        )
    instrument = Instrument("BTC/USD", AssetClass.CRYPTO)
    candidate = CandidateScanner().score_instrument(instrument, bars)
    proposal = TradeProposal("BTC/USD", AssetClass.CRYPTO, Side.BUY, 75, 73.5, 0.6, "mean_reversion")
    selected = experimental_candidate(candidate, (proposal,), config=PaperExperimentConfig(enabled=True))
    assert selected is not None


def test_champion_challenger_decision_and_outcome_are_persisted(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    decision_id = ledger.record_decision(
        pillar="alpaca_crypto",
        symbol="BTC/USD",
        strategy="mean_reversion",
        timeframe="15m",
        lane="EXPERIMENTAL_PAPER",
        decision="candidate",
        entry_price=100.0,
        edge=None,
        features={"score": 8.0},
    )
    ledger.record_outcome(decision_id, {"pnl": -1.0, "mfe": 2.0, "mae": -3.0})
    import sqlite3

    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        row = connection.execute(
            "SELECT lane, outcome_json FROM experiment_decisions WHERE id=?", (decision_id,)
        ).fetchone()
    assert row[0] == "EXPERIMENTAL_PAPER"
    assert "mfe" in row[1]


def test_unified_activity_observation_has_unique_experiment_id(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    experiment_id = ledger.record_activity(
        pillar="alpaca_crypto",
        engine="crypto",
        provider="alpaca-paper",
        market="BTC/USD",
        strategy="momentum",
        strategy_version="v1",
        model_version="m1",
        timeframe="15m",
        features={"volume_ratio": 1.4},
        raw_score=0.72,
        normalized_confidence=0.61,
        estimated_edge=0.01,
        candidate_status="REJECTED",
        qualification_result="NO",
        rejection_reason="risk_cap",
        risk_decision="BLOCK",
    )
    import sqlite3

    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        row = connection.execute(
            "SELECT experiment_id, market, raw_score, rejection_reason FROM activity_observations"
        ).fetchone()
    assert row == (experiment_id, "BTC/USD", 0.72, "risk_cap")
    assert experiment_id.startswith("EXP-")


def test_shadow_trade_is_provider_free_and_separate(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    shadow_id = ledger.record_shadow_trade(
        shadow_id="SHADOW-1", experiment_id="EXP-1", pillar="Crypto", strategy_id="crypto.momentum",
        market="BTC/USD", direction="BUY", hypothetical_entry=100.0, entry_at="2026-01-01T00:00:00+00:00",
        entry_reason="near threshold", qualification_score=0.58, prevented_by_threshold="confidence<0.60",
        hypothetical_stop=98.0, hypothetical_target=104.0, regime="TRENDING",
    )
    import sqlite3

    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        assert connection.execute("SELECT shadow_id, hypothetical_pnl FROM shadow_trades").fetchone() == (shadow_id, None)
        assert connection.execute("SELECT COUNT(*) FROM activity_observations").fetchone()[0] == 0


def test_candidate_and_signal_can_share_one_economic_experiment_id(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    kwargs = dict(
        pillar="alpaca_crypto", symbol="BTC/USD", strategy="momentum", timeframe="15m",
        lane="OBSERVATION", entry_price=100.0, edge=None, features={"score": 1.0}, experiment_id="EXP-ONE",
    )
    ledger.record_decision(**kwargs, decision="candidate")
    ledger.record_decision(**kwargs, decision="signal")
    import sqlite3

    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM experiment_decisions").fetchone()[0] == 2


def test_experimental_crypto_position_cap_is_bounded_to_twenty_percent():
    config = PaperExperimentConfig(enabled=True)
    assert experimental_position_quantity_cap(pillar_capital=1000.0, entry_price=100.0, config=config) * 100.0 == 200.0
