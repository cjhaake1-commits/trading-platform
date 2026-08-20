import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "publish_dashboard_snapshot.py"
SPEC = importlib.util.spec_from_file_location("publish_dashboard_snapshot", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


def test_snapshot_ignores_stale_ledger_capital_and_derives_internal_cash(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "read_portfolio",
        lambda _path: ({"equity": 4000.0, "cash": 4000.0, "peak_equity": 4000.0}, [], [], []),
    )
    monkeypatch.setattr(publisher, "read_activity", lambda _path: ([], {}))
    monkeypatch.setattr(
        publisher,
        "live_broker_positions",
        lambda _rows: (
            [{"pillar": "Stocks", "market_value": 1000.0, "unrealized_pnl": 100.0}],
            {
                "unrealized_pnl": 100.0,
                "gross_exposure": 1000.0,
                "alpaca_exposure": 1000.0,
                "metals_exposure": 0.0,
                "oanda_exposure": 0.0,
            },
        ),
    )

    snapshot = publisher.build_snapshot(Path("missing"), Path("missing"), Path("missing"))

    assert snapshot["portfolio"]["base_equity"] == 5000.0
    assert snapshot["cash_dashboard"]["original_capital"] == 5000.0
    assert snapshot["cash_dashboard"]["available_cash"] == 4000.0
    assert snapshot["cash_dashboard"]["unrealized_pnl"] == 100.0
    assert snapshot["cash_dashboard"]["net_trading_cash_generated"] == 0.0
    assert snapshot["cash_dashboard"]["realized_return"] == 0.0
    assert snapshot["runtime"]["autonomous_job_disabled"] is True
