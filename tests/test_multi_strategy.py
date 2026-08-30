from datetime import datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar
from autotrader.multi_strategy import StrategyEvaluation, aggregate_confluence, evaluate_strategies


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


def test_confluence_handles_hold_only_evaluations():
    evaluations = tuple(
        StrategyEvaluation("crypto.test", "BTC/USD", "15m", "HOLD", 0.0, 0.0, 0.0, 0.0, {}, True, False, "no signal")
        for _ in range(5)
    )
    decision = aggregate_confluence(evaluations)
    assert decision.direction == "HOLD"
