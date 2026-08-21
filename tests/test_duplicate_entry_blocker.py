from __future__ import annotations

from datetime import UTC, datetime

import autotrader.autonomous_paper as autonomous_paper_module
from autotrader.models import (
    AssetClass,
    Instrument,
    PortfolioState,
    Side,
    TradeIntent,
    TradeProposal,
)
from autotrader.portfolio_ledger import PortfolioLedger


def test_latest_unresolved_manifest_blocks_new_entry_even_if_latest_row_is_terminal(tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    unresolved_time = datetime(2026, 8, 21, 0, 55, tzinfo=UTC)
    terminal_time = datetime(2026, 8, 21, 1, 5, tzinfo=UTC)
    unresolved_fingerprint = ledger.manifest_fingerprint(
        {"symbol": "MSTR", "state": "order_pending"}
    )
    terminal_fingerprint = ledger.manifest_fingerprint({"symbol": "MSTR", "state": "filled"})

    ledger.save_entry_manifest(
        manifest_id="old-unresolved",
        created_at=unresolved_time,
        broker="alpaca-paper",
        environment="paper",
        pillar="Stocks",
        canonical_symbol="MSTR",
        broker_symbol="MSTR",
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
        lifecycle_state="order_pending",
        client_order_id_namespace="auto-old",
        fingerprint=unresolved_fingerprint,
        broker_order_id="order-old",
        submitted_quantity=1.0,
    )
    ledger.save_entry_manifest(
        manifest_id="new-terminal",
        created_at=terminal_time,
        broker="alpaca-paper",
        environment="paper",
        pillar="Stocks",
        canonical_symbol="MSTR",
        broker_symbol="MSTR",
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
        lifecycle_state="cancelled_unfilled",
        client_order_id_namespace="auto-new",
        fingerprint=terminal_fingerprint,
        broker_order_id="order-new",
        submitted_quantity=1.0,
        filled_quantity=0.0,
    )

    latest = ledger.latest_entry_manifest_for_symbol("MSTR", broker="alpaca-paper")
    unresolved = ledger.latest_unresolved_entry_manifest_for_symbol("MSTR", broker="alpaca-paper")

    assert latest is not None and latest["lifecycle_state"] == "cancelled_unfilled"
    assert unresolved is not None and unresolved["manifest_id"] == "old-unresolved"


def test_unresolved_manifest_blocks_duplicate_entry_in_autonomous_job(monkeypatch, tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_entry_manifest(
        manifest_id="manifest-1",
        created_at=datetime(2026, 8, 21, 0, 55, tzinfo=UTC),
        broker="alpaca-paper",
        environment="paper",
        pillar="Stocks",
        canonical_symbol="MSTR",
        broker_symbol="MSTR",
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
        lifecycle_state="order_pending",
        client_order_id_namespace="auto-20260821-MSTR",
        fingerprint=ledger.manifest_fingerprint({"symbol": "MSTR", "state": "order_pending"}),
        broker_order_id="order-1",
        submitted_quantity=1.0,
    )

    class Preflight:
        ready = True
        failed_checks: list[str] = []
        messages: list[str] = []
        portfolio = PortfolioState(equity=5000.0, cash=5000.0)
        peak_equity = 5000.0

    signal = autonomous_paper_module.RankedSignal(
        Instrument("MSTR", AssetClass.STOCK),
        12.0,
        TradeProposal(
            "MSTR",
            AssetClass.STOCK,
            Side.BUY,
            100.0,
            95.0,
            0.8,
            "unit-test",
            "unit-test",
            TradeIntent.ENTER,
        ),
        ("scanner",),
    )

    monkeypatch.setattr(
        autonomous_paper_module,
        "run_preflight",
        lambda **_kwargs: Preflight(),
    )
    monkeypatch.setattr(
        autonomous_paper_module.AutonomousPaperTradingJob,
        "_load_histories",
        lambda self, now: {signal.instrument: [1, 2, 3]},
    )
    monkeypatch.setattr(
        autonomous_paper_module,
        "choose_long_signal",
        lambda *args, **kwargs: signal,
    )
    monkeypatch.setattr(
        autonomous_paper_module,
        "submit_alpaca_paper_protected_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not submit")),
    )
    monkeypatch.setattr(
        autonomous_paper_module,
        "submit_alpaca_paper_crypto_market_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not submit")),
    )
    monkeypatch.setattr(
        autonomous_paper_module,
        "submit_oanda_practice_market_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not submit")),
    )

    job = autonomous_paper_module.AutonomousPaperTradingJob(
        autonomous_paper_module.AutonomousPaperConfig(
            ledger_path=str(ledger.path),
            idempotency_path=str(tmp_path / "idempotency.db"),
            alpaca_universe=("MSTR",),
            oanda_universe=(),
            crypto_universe=(),
        )
    )
    result = job.run(datetime.now(UTC))

    assert result.data["duplicate_skips"]
    assert result.data["duplicate_skips"][0]["reason"] == (
        "existing unresolved manifest blocks duplicate entry"
    )
