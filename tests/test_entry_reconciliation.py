from __future__ import annotations

from datetime import UTC, datetime

import autotrader.autonomous_paper as autonomous_paper_module
import autotrader.order_test_app as order_test_app_module
from autotrader.models import AssetClass
from autotrader.portfolio_ledger import PortfolioLedger


def test_sync_returns_reconciliation_pending_when_position_lags_after_fill(monkeypatch, tmp_path):
    responses = iter(
        [
            {"status": "filled", "id": "order-1"},
            {"status": "filled", "id": "order-1"},
        ]
    )

    def fake_request_json(url, method, headers, body=None, timeout=15.0):
        if url.endswith("/v2/orders/order-1"):
            return next(responses), {}
        raise AssertionError(f"unexpected url {url}")

    def fake_alpaca_open_positions():
        class Result:
            ok = True
            broker = "alpaca-paper"
            message = "ok"
            details = {"positions": []}

        return Result()

    monkeypatch.setattr(order_test_app_module, "_request_json", fake_request_json)
    monkeypatch.setattr(order_test_app_module, "_alpaca_credentials", lambda: ("key", "secret", "https://paper-api.alpaca.markets"))
    monkeypatch.setattr(order_test_app_module, "alpaca_open_positions", fake_alpaca_open_positions)

    sync = order_test_app_module._sync_submitted_position(
        broker="alpaca",
        symbol="MSTR",
        stop_price=100.0,
        ledger_path=str(tmp_path / "portfolio.db"),
        initial_equity=5000.0,
        expected_quantity=1.0,
        asset_class=AssetClass.STOCK,
        attempts=2,
        delay_seconds=0.0,
        broker_order_id="order-1",
    )

    assert sync["reconciliation_status"] == "filled_position_pending"
    assert sync["quantity"] is None
    assert sync["order_status"] == "filled"


def test_sync_does_not_persist_ledger_before_reconciliation(monkeypatch, tmp_path):
    def fake_request_json(url, method, headers, body=None, timeout=15.0):
        if url.endswith("/v2/orders/order-1"):
            return {"status": "filled", "id": "order-1"}, {}
        raise AssertionError(f"unexpected url {url}")

    def fake_alpaca_open_positions():
        class Result:
            ok = True
            broker = "alpaca-paper"
            message = "ok"
            details = {"positions": []}

        return Result()

    monkeypatch.setattr(order_test_app_module, "_request_json", fake_request_json)
    monkeypatch.setattr(order_test_app_module, "_alpaca_credentials", lambda: ("key", "secret", "https://paper-api.alpaca.markets"))
    monkeypatch.setattr(order_test_app_module, "alpaca_open_positions", fake_alpaca_open_positions)

    ledger_path = tmp_path / "portfolio.db"
    sync = order_test_app_module._sync_submitted_position(
        broker="alpaca",
        symbol="MSTR",
        stop_price=100.0,
        ledger_path=str(ledger_path),
        initial_equity=5000.0,
        expected_quantity=1.0,
        asset_class=AssetClass.STOCK,
        attempts=1,
        delay_seconds=0.0,
        broker_order_id="order-1",
    )

    assert sync["quantity"] is None
    ledger = PortfolioLedger(ledger_path)
    assert ledger.load_portfolio() is None


def test_autonomous_job_blocks_duplicate_manifest_when_reconciliation_pending(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        manifest_id="manifest-1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        broker="alpaca-paper",
        environment="paper",
        pillar="alpaca_equities",
        canonical_symbol="MSTR",
        broker_symbol="MSTR",
        side="buy",
        model_version="five_pillar_baseline_v1",
        strategy_version="unit-test",
        confidence=0.7,
        regime=None,
        approved_entry=100.0,
        requested_quantity=1.0,
        approved_notional=100.0,
        approved_stop=95.0,
        approved_target=None,
        approved_dollar_risk=5.0,
        allocation_at_approval=100.0,
        portfolio_risk_at_approval=100.0,
        risk_engine_decision="approved",
        lifecycle_state="order_submitted",
        client_order_id_namespace="auto-20260820-MSTR",
        fingerprint="fingerprint-1",
        broker_order_id="order-1",
        submitted_quantity=1.0,
        metadata={"symbol": "MSTR"},
    )

    class FakeJob:
        def __init__(self, config):
            self.config = config

        def run(self, now):
            return autonomous_paper_module.JobResult(
                True,
                "Autonomous paper cycle completed",
                {"entries": [], "duplicate_skips": []},
            )

    monkeypatch.setattr(autonomous_paper_module, "AutonomousPaperTradingJob", FakeJob)
    loaded = ledger.latest_entry_manifest_for_symbol("MSTR", broker="alpaca-paper")
    assert loaded is not None
    assert loaded["lifecycle_state"] == "order_submitted"
