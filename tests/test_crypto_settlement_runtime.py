from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from autotrader.crypto_settlement_runtime import settle_from_runtime
from autotrader.paper_experiment import PaperExperimentLedger


def test_runtime_settlement_is_provider_free_and_horizon_aware(tmp_path):
    db = tmp_path / "paper.db"
    ledger = PaperExperimentLedger(db)
    occurred = datetime(2026, 9, 5, tzinfo=UTC)
    ledger.record_counterfactual(
        occurred_at=occurred,
        symbol="BTC/USD",
        champion_decision="REJECT",
        challenger_decision="ACCEPT",
        entry_price=100,
        quantity=1,
        stop_price=90,
        target_price=110,
        features={"estimated_cost_rate": 0.01},
        candidate_identity="O1",
    )
    pending = settle_from_runtime(
        bars_by_symbol={"BTC/USD": []},
        now=occurred + timedelta(minutes=1),
        ledger_path=db,
        report_path=tmp_path / "p.json",
    )
    assert pending["counts"].get("pending_outcome", 0) >= 1 and pending["provider_orders"] == 0
    bars = [SimpleNamespace(timestamp=occurred + timedelta(minutes=1), close=101, high=102, low=99)]
    settled = settle_from_runtime(
        bars_by_symbol={"BTC/USD": bars},
        now=occurred + timedelta(minutes=1),
        ledger_path=db,
        report_path=tmp_path / "p.json",
    )
    assert settled["provider_orders"] == 0
