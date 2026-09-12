from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, MarketBar
from autotrader.paper_experiment import PaperExperimentLedger
from autotrader.watchdog_dispatch import dispatch_counterfactuals, dispatch_reconciliation, run_production_dispatch


def test_production_reconciliation_dispatch_is_read_only():
    seen = []
    out = dispatch_reconciliation(
        {p: (lambda p=p: seen.append(p) or {"ok": True}) for p in ("Alpaca", "OANDA", "Saxo", "Kalshi")}
    )
    assert all(x["state"] == "RECOVERED" for x in out) and set(seen) == {"Alpaca", "OANDA", "Saxo", "Kalshi"}
    assert all(x["trading_side_effects"] == "NONE" for x in out)


def test_production_counterfactual_dispatch_settles_due(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "e.db")
    at = datetime(2026, 1, 1, tzinfo=UTC)
    ledger.record_counterfactual(
        symbol="BTC/USD",
        occurred_at=at,
        champion_decision="REJECT",
        challenger_decision="REJECT",
        entry_price=100,
        quantity=1,
        stop_price=99,
        target_price=102,
        features={"estimated_cost_rate": 0.01},
        candidate_identity="x",
    )
    bars = [
        MarketBar("BTC/USD", AssetClass.CRYPTO, at + timedelta(minutes=i), 100 + i, 102 + i, 99 + i, 101 + i)
        for i in range(1, 8)
    ]
    out = dispatch_counterfactuals(ledger=ledger, bars_by_symbol={"BTC/USD": bars}, now=at + timedelta(hours=2))
    assert out["settlement"]["evaluated"] == 1 and out["trading_side_effects"] == "NONE"


def test_production_watchdog_entrypoint_writes_dispatch(tmp_path):
    out = run_production_dispatch(
        readers={p: (lambda: {"ok": True}) for p in ("Alpaca", "OANDA", "Saxo", "Kalshi")},
        output=tmp_path / "dispatch.json",
    )
    assert out["trading_side_effects"] == "NONE" and (tmp_path / "dispatch.json").exists()
