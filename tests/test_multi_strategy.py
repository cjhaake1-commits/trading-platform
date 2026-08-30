from datetime import datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar
from autotrader.multi_strategy import StrategyEvaluation, aggregate_confluence, evaluate_proposals, evaluate_strategies


def _bars():
    start = datetime(2026, 1, 1)
    return [MarketBar("BTC/USD", AssetClass.CRYPTO, start + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100 + i, 1000) for i in range(30)]


def test_crypto_evaluates_five_strategies_and_aggregates_one_opportunity():
    evaluations = evaluate_strategies(Instrument("BTC/USD", AssetClass.CRYPTO), _bars(), 30.0)
    assert len(evaluations) == 5
    decision = aggregate_confluence(evaluations)
    assert decision.market == "BTC/USD"
    assert decision.long_votes + decision.short_votes + decision.hold_votes == 5
    assert len(decision.strategy_votes) == 5


def test_confluence_preserves_disagreement():
    evaluations = evaluate_strategies(Instrument("BTC/USD", AssetClass.CRYPTO), _bars(), 30.0)
    decision = aggregate_confluence(evaluations)
    assert decision.dispersion >= 0.0


def test_comparable_tied_directional_votes_are_explicit_conflict():
    evaluations = tuple(
        StrategyEvaluation(f"s{i}", "BTC/USD", "15m", direction, 1.0, 0.5, 0.01, 0.005, {}, True, True)
        for i, direction in enumerate(("BUY", "SELL", "HOLD"))
    )
    decision = aggregate_confluence(evaluations)
    assert decision.direction == "CONFLICT"
    assert decision.conflict_state == "TIED_COMPARABLE_CONFIDENCE"


def test_confluence_handles_hold_only_evaluations():
    evaluations = tuple(
        StrategyEvaluation("crypto.test", "BTC/USD", "15m", "HOLD", 0.0, 0.0, 0.0, 0.0, {}, True, False, "no signal")
        for _ in range(5)
    )
    decision = aggregate_confluence(evaluations)
    assert decision.direction == "HOLD"


def test_strategy_methods_are_not_aliases_and_relative_strength_is_explicitly_unavailable():
    evaluations = evaluate_strategies(Instrument("BTC/USD", __import__("autotrader.models", fromlist=["AssetClass"]).AssetClass.CRYPTO), _bars(), 30.0)
    methods = {item.strategy_id.rsplit(".", 1)[-1]: item.features["source_method"] for item in evaluations}
    assert methods["momentum"] == "momentum"
    assert methods["trend_following"] == "trend_following"
    assert methods["relative_strength"] == "INSUFFICIENT_DATA"
    assert next(item for item in evaluations if item.strategy_id.endswith("relative_strength")).rejection_reason == "INSUFFICIENT_DATA"
    assert all(item.estimated_edge is None and item.expected_value is None for item in evaluations)
    assert all(item.edge_proxy is not None and item.ev_proxy is not None for item in evaluations)
    assert next(item for item in evaluations if item.strategy_id.endswith("relative_strength")).data_quality == "INSUFFICIENT_DATA"
    assert all(item.data_quality == "FRESH" for item in evaluations if not item.strategy_id.endswith("relative_strength"))
    assert all(item.regime in {"TRENDING", "RANGE", "HIGH_VOL", "UNKNOWN"} for item in evaluations)


def test_confluence_persists_insufficient_data_and_edge_proxy_aggregates():
    evaluations = (
        StrategyEvaluation("a", "BTC/USD", "15m", "BUY", 80, 0.8, None, None, {}, True, True, edge_proxy=0.4, data_quality="FRESH"),
        StrategyEvaluation("b", "BTC/USD", "15m", "HOLD", 0, 0.0, None, None, {}, True, False, rejection_reason="INSUFFICIENT_DATA", edge_proxy=0.0, data_quality="INSUFFICIENT_DATA"),
    )
    decision = aggregate_confluence(evaluations)
    assert decision.insufficient_data_count == 1
    assert decision.aggregate_edge_proxy == 0.2
    assert all("regime" in vote for vote in decision.strategy_votes)


def test_asset_specific_proposals_normalize_missing_votes_without_first_buy_bias():
    instrument = Instrument("GLD", AssetClass.ETF)
    proposals = {"momentum": None, "breakout": None}
    evaluations = evaluate_proposals(instrument, _bars(), proposals, candidate_score=80.0)
    assert [item.direction for item in evaluations] == ["HOLD", "HOLD"]
    assert all(item.rejection_reason == "NO_STRATEGY_SIGNAL" for item in evaluations)
    assert all(item.estimated_edge is None and item.expected_value is None for item in evaluations)
    assert aggregate_confluence(evaluations).direction == "HOLD"


def test_unavailable_relative_strength_is_insufficient_data():
    evaluations = evaluate_proposals(
        Instrument("GLD", AssetClass.ETF), _bars(), {"relative_strength": None}, candidate_score=80.0
    )
    assert evaluations[0].rejection_reason == "INSUFFICIENT_DATA"
    assert evaluations[0].data_quality == "INSUFFICIENT_DATA"
