import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

from autotrader.dashboard_health import runtime_status_labels

SNAPSHOT_PATH = Path(__file__).parents[1] / "scripts" / "publish_dashboard_snapshot.py"
SNAPSHOT_SPEC = importlib.util.spec_from_file_location("publish_dashboard_snapshot", SNAPSHOT_PATH)
assert SNAPSHOT_SPEC is not None and SNAPSHOT_SPEC.loader is not None
publisher = importlib.util.module_from_spec(SNAPSHOT_SPEC)
sys.modules[SNAPSHOT_SPEC.name] = publisher
SNAPSHOT_SPEC.loader.exec_module(publisher)

DASHBOARD_PATH = Path(__file__).parents[1] / "src" / "autotrader" / "dashboard_app.py"
DASHBOARD_SPEC = importlib.util.spec_from_file_location("dashboard_app", DASHBOARD_PATH)
assert DASHBOARD_SPEC is not None and DASHBOARD_SPEC.loader is not None
dashboard_app = importlib.util.module_from_spec(DASHBOARD_SPEC)
sys.modules[DASHBOARD_SPEC.name] = dashboard_app
DASHBOARD_SPEC.loader.exec_module(dashboard_app)


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


def test_dashboard_separates_healthy_runtime_from_disarmed_execution(monkeypatch):
    now = datetime.now(UTC).isoformat()
    monkeypatch.setattr(
        publisher,
        "read_json",
        lambda _path: {
            "mode": "paper",
            "healthy": True,
            "autonomous_enabled": False,
            "execution_state": "disarmed",
            "last_heartbeat_at": now,
            "jobs": {
                "health": {"disabled": False, "consecutive_failures": 0, "last_error": None},
                "autonomous-paper-trading": {
                    "disabled": True,
                    "last_error": "Execution disarmed",
                },
            },
        },
    )
    monkeypatch.setattr(publisher, "read_portfolio", lambda _path: ({}, [], [], []))
    monkeypatch.setattr(publisher, "read_activity", lambda _path: ([], {}))
    monkeypatch.setattr(
        publisher,
        "live_broker_positions",
        lambda _rows: (
            [],
            {
                "unrealized_pnl": 0.0,
                "gross_exposure": 0.0,
                "alpaca_exposure": 0.0,
                "metals_exposure": 0.0,
                "oanda_exposure": 0.0,
            },
        ),
    )

    runtime = publisher.build_snapshot(Path("status"), Path("ledger"), Path("audit"))["runtime"]

    assert runtime["healthy"] is True
    assert runtime["autonomous_enabled"] is False
    assert runtime["execution_state"] == "disarmed"
    assert runtime["last_error"] is None
    assert runtime["live_trading_enabled"] is False
    assert runtime_status_labels(runtime) == {
        "runtime_health": "Healthy",
        "autonomous_paper_trading": "DISARMED",
        "live_trading": "DISABLED",
    }


def test_dashboard_labels_healthy_armed_paper_and_unhealthy_disarmed():
    assert runtime_status_labels(
        {"healthy": True, "autonomous_enabled": True, "execution_state": "armed_paper"}
    )["autonomous_paper_trading"] == "ARMED (PAPER)"
    assert runtime_status_labels(
        {"healthy": False, "autonomous_enabled": False, "execution_state": "faulted"}
    ) == {
        "runtime_health": "Faulted",
        "autonomous_paper_trading": "DISARMED",
        "live_trading": "DISABLED",
    }


def test_snapshot_exposes_crypto_reconciliation_and_protection_state(monkeypatch):
    monkeypatch.setattr(
        dashboard_app,
        "_read_json",
        lambda _path: {
            "mode": "paper",
            "healthy": True,
            "autonomous_enabled": False,
            "execution_state": "disarmed",
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
            "jobs": {"health": {"disabled": False, "consecutive_failures": 0, "last_error": None}},
        },
    )
    monkeypatch.setattr(
        publisher,
        "read_portfolio",
        lambda _path: (
            {"equity": 5000.0, "cash": 4000.0, "peak_equity": 5000.0},
            [
                {
                    "symbol": "ETHUSD",
                    "broker": "Alpaca Paper",
                    "asset_class": "us_equity",
                    "quantity": 0.425654496,
                    "average_price": 2345.3,
                    "current_price": 2342.261,
                    "stop_price": None,
                    "market_value": 996.993925,
                    "unrealized_pnl": -1.293564,
                    "unrealized_pct": -0.0013,
                    "risk_dollars": 0.0,
                }
            ],
            [],
            [],
            [
                {
                    "symbol": "ETH/USD",
                    "lifecycle_state": "unprotected_position",
                    "reconciliation_status": "fractional_reconciliation",
                    "reconciliation_difference": 0.001066804,
                    "reconciliation_tolerance": 0.005,
                    "protection_state": "failed",
                    "protection_quantity": None,
                    "stop_price": 2300.0,
                }
            ],
        ),
    )
    monkeypatch.setattr(publisher, "read_activity", lambda _path: ([], {}))
    monkeypatch.setattr(
        publisher,
        "live_broker_positions",
        lambda _rows: (
            [
                {
                    "pillar": "Stocks/Crypto",
                    "broker": "Alpaca Paper",
                    "symbol": "ETHUSD",
                    "asset_class": "us_equity",
                    "quantity": 0.425654496,
                    "average_price": 2345.3,
                    "current_price": 2342.261,
                    "stop_price": None,
                    "market_value": 996.993925,
                    "unrealized_pnl": -1.293564,
                    "unrealized_pct": -0.0013,
                    "risk_dollars": 0.0,
                }
            ],
            {
                "unrealized_pnl": -1.293564,
                "gross_exposure": 996.993925,
                "alpaca_exposure": 996.993925,
                "metals_exposure": 0.0,
                "oanda_exposure": 0.0,
            },
        ),
    )

    snapshot = publisher.build_snapshot(Path("status"), Path("ledger"), Path("audit"))
    eth = snapshot["positions"][0]

    assert eth["crypto_lifecycle_state"] == "unprotected_position"
    assert eth["crypto_reconciliation_status"] == "fractional_reconciliation"
    assert eth["crypto_protection_state"] == "failed"
    assert eth["crypto_stop_price"] == 2300.0


def test_dashboard_renders_learning_baseline_and_status(monkeypatch):
    monkeypatch.setattr(
        dashboard_app,
        "_read_json",
        lambda _path: {
            "mode": "paper",
            "healthy": True,
            "autonomous_enabled": False,
            "execution_state": "disarmed",
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
            "jobs": {"health": {"disabled": False, "consecutive_failures": 0, "last_error": None}},
        },
    )
    monkeypatch.setattr(
        dashboard_app,
        "_read_portfolio",
        lambda _path: {"portfolio": {}, "positions": [], "fills": 0, "brokers": []},
    )
    monkeypatch.setattr(dashboard_app, "_read_audit", lambda _path, limit=30: [])
    monkeypatch.setattr(
        dashboard_app,
        "_read_learning",
        lambda: {
            "stats": {"completed_trades": 20, "sample_status": "adaptive"},
            "parameters": {"minimum_candidate_score": 5.0},
            "model_state": {
                "baseline_version": "five_pillar_baseline_v1",
                "active_version": "challenger_20260820010101",
                "promotions": [{"timestamp": "2026-08-20T01:01:01+00:00", "to": "challenger_20260820010101"}],
            },
            "history": [
                {
                    "parameter": "minimum_candidate_score",
                    "old_value": 5.0,
                    "new_value": 4.9,
                    "reason": "bounded realized-outcome adaptation",
                }
            ],
        },
    )
    html = dashboard_app.render_dashboard(Path("status"), Path("ledger"), Path("audit"))

    assert "five_pillar_baseline_v1" in html
    assert "challenger_20260820010101" in html
    assert "adaptive" in html
    assert "minimum_candidate_score" in html
