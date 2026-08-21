from __future__ import annotations

import autotrader.alpaca_backlog as alpaca_backlog
from autotrader.portfolio_ledger import PortfolioLedger


def _manifest_kwargs(symbol: str, state: str, order_id: str, created_at: str):
    return dict(
        manifest_id=f"{symbol}-{state}-{order_id}",
        created_at=created_at,
        broker="alpaca-paper",
        environment="paper",
        pillar="Stocks",
        canonical_symbol=symbol,
        broker_symbol=symbol,
        side="buy",
        model_version="five_pillar_baseline_v1",
        strategy_version="unit-test",
        confidence=0.8,
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
        lifecycle_state=state,
        client_order_id_namespace=f"auto-{symbol}",
        fingerprint=f"fingerprint-{symbol}-{state}-{order_id}",
        broker_order_id=order_id,
        submitted_quantity=1.0,
    )


def test_bulk_snapshot_reuses_one_positions_open_and_recent_pull(monkeypatch):
    calls: list[str] = []

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        calls.append(url)
        if url.endswith("/v2/positions"):
            return ([{"symbol": "MSTR", "qty": "1", "avg_entry_price": "100"}], {})
        if "status=open" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "new",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        if "status=all" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "new",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    snapshot = alpaca_backlog.fetch_alpaca_bulk_snapshot(
        [
            {"created_at": "2026-08-21T00:55:00+00:00"},
            {"created_at": "2026-08-21T01:00:00+00:00"},
        ],
        request_fn=fake_request,
    )

    assert len(calls) == 3
    assert snapshot.budget.requests == 3
    assert "o1" in snapshot.orders_by_id


def test_terminal_zero_fill_cleanup_can_be_applied(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_submitted", "o1", "2026-08-21T00:55:00+00:00")
    )

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        if "status=all" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    result = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=True,
        request_fn=fake_request,
    )
    manifest = ledger.latest_entry_manifest_for_symbol("MSTR", broker="alpaca-paper")

    assert result.unresolved_before == 1
    assert result.classifications[0].lifecycle_state == "cancelled_unfilled"
    assert manifest is not None and manifest["lifecycle_state"] == "cancelled_unfilled"


def test_duplicate_managed_orders_only_cancel_managed_orders(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_pending", "o1", "2026-08-21T00:55:00+00:00")
    )
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_pending", "o2", "2026-08-21T00:56:00+00:00")
    )

    cancelled: list[str] = []

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "new",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    },
                    {
                        "id": "o2",
                        "symbol": "MSTR",
                        "status": "new",
                        "filled_qty": "0",
                        "client_order_id": "auto-2",
                    },
                    {
                        "id": "manual",
                        "symbol": "MSTR",
                        "status": "new",
                        "filled_qty": "0",
                        "client_order_id": "manual-1",
                    },
                ],
                {},
            )
        if "status=all" in url:
            return ([], {})
        if method == "DELETE":
            cancelled.append(url.rsplit("/", 1)[-1])
            return ({}, {})
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    result = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=True,
        request_fn=fake_request,
    )

    assert set(cancelled) == {"o1", "o2"}
    assert result.telemetry["duplicate_orders_cancelled"] == 2


def test_request_budget_exhaustion_defers_safely(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_pending", "o1", "2026-08-21T00:55:00+00:00")
    )

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if budget is not None and budget.requests >= 1:
            raise RuntimeError("Broker request budget exceeded")
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return ([], {})
        if "status=all" in url:
            return ([], {})
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    result = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=False,
        request_fn=fake_request,
        budget_limit=1,
    )

    assert result.telemetry["broker_deferred"] >= 1
    assert result.unresolved_after >= 1


def test_incomplete_recent_snapshot_becomes_reconciliation_deferred(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_submitted", "missing-order", "2026-08-21T00:55:00+00:00")
    )

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return ([], {})
        if "status=all" in url:
            raise RuntimeError("Broker request budget exceeded")
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    result = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=False,
        request_fn=fake_request,
    )

    assert result.classifications[0].lifecycle_state == "reconciliation_deferred"
    assert result.telemetry["manifests_deferred"] == 1


def test_canceled_zero_fill_is_not_counted_in_learning_or_accounting(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_submitted", "o1", "2026-08-21T00:55:00+00:00")
    )

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        if "status=all" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    before = ledger.load_portfolio()
    result = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=True,
        request_fn=fake_request,
    )
    after = ledger.load_portfolio()

    assert before == after
    assert result.classifications[0].lifecycle_state == "cancelled_unfilled"


def test_rerun_is_idempotent(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        **_manifest_kwargs("MSTR", "order_submitted", "o1", "2026-08-21T00:55:00+00:00")
    )

    def fake_request(url, *, method, headers, body=None, timeout=15.0, budget=None):
        if url.endswith("/v2/positions"):
            return ([], {})
        if "status=open" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        if "status=all" in url:
            return (
                [
                    {
                        "id": "o1",
                        "symbol": "MSTR",
                        "status": "canceled",
                        "filled_qty": "0",
                        "client_order_id": "auto-1",
                    }
                ],
                {},
            )
        raise AssertionError(url)

    monkeypatch.setattr(
        alpaca_backlog,
        "_alpaca_auth",
        lambda: ("key", "secret", "https://paper-api.alpaca.markets"),
    )
    first = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=True,
        request_fn=fake_request,
    )
    second = alpaca_backlog.reconcile_alpaca_equity_backlog(
        tmp_path / "portfolio.db",
        apply_paper_cleanup=True,
        request_fn=fake_request,
    )

    assert first.unresolved_before == 1
    assert second.unresolved_before == 0
