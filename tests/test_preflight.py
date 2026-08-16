from autotrader.brokers.connectivity import ConnectivityResult
from autotrader.brokers.safety import BrokerSafetyResult
from autotrader import preflight


def test_preflight_ready_with_empty_reconciled_brokers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        preflight,
        "test_alpaca_paper",
        lambda: ConnectivityResult(
            "alpaca-paper",
            True,
            "ok",
            {"status": "ACTIVE"},
        ),
    )
    monkeypatch.setattr(
        preflight,
        "test_oanda_practice",
        lambda: ConnectivityResult(
            "oanda-practice",
            True,
            "ok",
            {"account_ids": ["practice-1"], "selected_account_id": "practice-1"},
        ),
    )
    monkeypatch.setattr(
        preflight,
        "alpaca_open_positions",
        lambda: BrokerSafetyResult("alpaca-paper", True, "ok", {"positions": []}),
    )
    monkeypatch.setattr(
        preflight,
        "oanda_open_positions",
        lambda: BrokerSafetyResult("oanda-practice", True, "ok", {"positions": []}),
    )

    report = preflight.run_preflight(
        ledger_path=tmp_path / "portfolio.db",
        idempotency_path=tmp_path / "idempotency.db",
        initial_equity=2000.0,
    )

    assert report.ready
    assert not report.failed_checks
    assert report.portfolio.equity == 2000.0
    assert report.checks["reconciliation_ok"]


def test_preflight_blocks_ambiguous_oanda_account_selection(tmp_path, monkeypatch):
    monkeypatch.delenv("OANDA_PRACTICE_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        preflight,
        "test_alpaca_paper",
        lambda: ConnectivityResult(
            "alpaca-paper",
            True,
            "ok",
            {"status": "ACTIVE"},
        ),
    )
    monkeypatch.setattr(
        preflight,
        "test_oanda_practice",
        lambda: ConnectivityResult(
            "oanda-practice",
            True,
            "ok",
            {"account_ids": ["practice-1", "practice-2"], "selected_account_id": "practice-1"},
        ),
    )
    monkeypatch.setattr(
        preflight,
        "alpaca_open_positions",
        lambda: BrokerSafetyResult("alpaca-paper", True, "ok", {"positions": []}),
    )
    monkeypatch.setattr(
        preflight,
        "oanda_open_positions",
        lambda: BrokerSafetyResult("oanda-practice", True, "ok", {"positions": []}),
    )

    report = preflight.run_preflight(
        ledger_path=tmp_path / "portfolio.db",
        idempotency_path=tmp_path / "idempotency.db",
    )

    assert not report.ready
    assert not report.checks["oanda_account_selection_unambiguous"]
    assert "oanda_account_selection_unambiguous" in report.failed_checks
