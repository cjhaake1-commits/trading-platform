from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, MarketBar
from autotrader.paper_experiment import PaperExperimentLedger


def _bars(symbol: str, start: datetime) -> list[MarketBar]:
    return [
        MarketBar(symbol, AssetClass.CRYPTO, start + timedelta(minutes=i), 100 + i, 102 + i, 99 + i, 101 + i)
        for i in range(1, 8)
    ]


def test_counterfactual_deduplicates_and_resolves_horizons(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    occurred = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = {
        "symbol": "BTC/USD", "occurred_at": occurred, "champion_decision": "REJECT",
        "challenger_decision": "ACCEPT", "entry_price": 100.0, "quantity": 1.0,
        "stop_price": 99.0, "target_price": 102.0, "features": {"estimated_cost_rate": 0.01},
        "candidate_identity": "candidate-1",
    }
    first = ledger.record_counterfactual(**kwargs)
    second = ledger.record_counterfactual(**kwargs)
    assert first == second
    counts = ledger.resolve_counterfactuals({"BTC/USD": _bars("BTC/USD", occurred)}, now=occurred + timedelta(hours=2))
    assert counts["evaluated"] == 1
    summary = ledger.counterfactual_summary()
    assert summary["observations"] == 1
    assert summary["challenger"]["observations"] == 1
    assert summary["challenger"]["expectancy"] is not None


def test_counterfactual_missing_data_is_not_fabricated(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    occurred = datetime(2026, 1, 1, tzinfo=UTC)
    ledger.record_counterfactual(
        symbol="ETH/USD", occurred_at=occurred, champion_decision="ACCEPT",
        challenger_decision="REJECT", entry_price=100.0, quantity=1.0,
        stop_price=99.0, target_price=102.0, features={}, candidate_identity="candidate-2",
    )
    counts = ledger.resolve_counterfactuals({}, now=occurred + timedelta(hours=2))
    assert counts["insufficient_data"] == 1
    summary = ledger.counterfactual_summary()
    assert summary["champion"]["pnl"] == 0.0
