import pytest

from autotrader.strategy_registry import StrategyDefinition, StrategyRegistry


def _definition() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="crypto.momentum",
        pillar="Crypto",
        version="v1",
        description="test",
        timeframe="15m",
        required_data=("bars",),
        risk_profile="paper",
        capital_limit=1000.0,
        minimum_sample_size=2,
    )


def test_registry_persists_scorecard_and_requires_evidence(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.register(_definition())
    assert registry.promotion_status("crypto.momentum") == "INSUFFICIENT_EVIDENCE"
    registry.record_observation("crypto.momentum", outcome=2.0)
    registry.record_observation("crypto.momentum", outcome=-1.0)
    reloaded = StrategyRegistry(tmp_path / "registry.json")
    assert reloaded.scorecards["crypto.momentum"].trades == 2
    assert reloaded.scorecards["crypto.momentum"].expectancy == 0.5
    assert reloaded.promotion_status("crypto.momentum") == "ELIGIBLE_FOR_REVIEW"


def test_registry_rejects_version_change_and_invalid_status(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    registry.register(_definition())
    with pytest.raises(ValueError, match="different version"):
        registry.register(_definition().__class__(**{**_definition().__dict__, "version": "v2"}))
    with pytest.raises(ValueError, match="invalid strategy status"):
        registry.register(_definition().__class__(**{**_definition().__dict__, "strategy_id": "x", "status": "LIVE"}))
