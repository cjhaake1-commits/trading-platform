from datetime import UTC, datetime, timedelta

import pytest

from autotrader.brokers.saxo_sim import SaxoOrderResult
from autotrader.international_trading import (
    INTERNATIONAL_CURRENT_EPOCH,
    INTERNATIONAL_LEGACY_EPOCH,
    InternationalExecutionPolicy,
    InternationalExecutionService,
    InternationalOrderSpec,
    InternationalTradeHistory,
)
from autotrader.learning import RealizedOutcomeLearner
from autotrader.models import AssetClass, PortfolioState, Position, Side, TradeProposal
from autotrader.pillar_jobs import InternationalPaperTradingJob


class FakeSaxoBroker:
    def __init__(self, result=None):
        self.orders = []
        self.result = result or SaxoOrderResult(True, "sim-order-1", "accepted", 100.1, 0.25)

    def submit_order(self, order):
        self.orders.append(order)
        return self.result


def spec(**proposal_overrides):
    proposal_data = {
        "symbol": "AIR:xpar",
        "asset_class": AssetClass.STOCK,
        "side": Side.BUY,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "confidence": 0.8,
        "source": "international-model",
        "requested_quantity": 2.0,
    }
    proposal_data.update(proposal_overrides)
    return InternationalOrderSpec(
        proposal=TradeProposal(**proposal_data),
        account_key="sim-account-key",
        uic=12345,
        saxo_asset_type="Stock",
        target_price=110.0,
        strategy_version="model-v2",
    )


def portfolio(**overrides):
    values = {"equity": 4000.0, "cash": 4000.0}
    values.update(overrides)
    return PortfolioState(**values)


def service(tmp_path, broker=None, policy=None):
    broker = broker or FakeSaxoBroker()
    history = InternationalTradeHistory(tmp_path / "ledger.db")
    return InternationalExecutionService(broker, history, policy=policy), broker, history


def test_current_epoch_is_restart_safe_and_legacy_rows_are_excluded(tmp_path):
    path = tmp_path / "ledger.db"
    history = InternationalTradeHistory(path)
    trade_id = history.record_proposal(spec(), quantity=1, decision="approved", rejection_reason=None, now=datetime.now(UTC))
    with history._connect() as connection:
        connection.execute(
            "UPDATE international_trades SET allocation_epoch = ?, status = 'executed', "
            "order_id = 'legacy-order', closed_at = NULL WHERE id = ?",
            (INTERNATIONAL_LEGACY_EPOCH, trade_id),
        )
    restarted = InternationalTradeHistory(path)
    assert restarted.current_epoch_order_ids() == set()
    assert restarted.legacy_order_ids() == {"legacy-order"}


def test_new_execution_is_tagged_to_current_epoch(tmp_path):
    execution, _, history = service(tmp_path)
    result = execution.execute(spec(), portfolio(), international_deployed=0)
    assert result.submitted
    record = history.records()[0]
    assert record["allocation_epoch"] == INTERNATIONAL_CURRENT_EPOCH


def test_same_symbol_does_not_prove_current_epoch_ownership(tmp_path):
    history = InternationalTradeHistory(tmp_path / "ledger.db")
    with history._connect() as connection:
        connection.execute(
            "INSERT INTO international_trades (proposed_at, broker, pillar, instrument, side, proposed_entry, "
            "stop_price, quantity, notional, model_confidence, model_version, strategy_version, risk_decision, "
            "status, order_id, allocation_epoch) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), "saxo-sim", "International", "AIR:xpar", "BUY", 100, 95, 1, 100,
             .8, "m", "s", "approved", "executed", "old-air", INTERNATIONAL_LEGACY_EPOCH),
        )
    assert "old-air" not in history.current_epoch_order_ids()


def test_legacy_inventory_is_diagnostic_not_current_economics(tmp_path):
    history = InternationalTradeHistory(tmp_path / "ledger.db")
    records = history.records()
    assert len(records) == 0
    assert history.current_epoch_order_ids() == set()


def test_risk_rejection_prevents_broker_submission_and_is_logged(tmp_path):
    execution, broker, history = service(tmp_path)
    full_positions = {f"P{i}": Position(f"P{i}", AssetClass.STOCK, 1, 10, 9) for i in range(6)}

    result = execution.execute(spec(), portfolio(positions=full_positions), international_deployed=0)

    assert not result.approved
    assert not result.submitted
    assert broker.orders == []
    record = history.records()[0]
    assert record["risk_decision"] == "rejected"
    assert "Maximum open positions" in record["rejection_reason"]
    assert record["strategy_version"] == "model-v2"


def test_explicit_stop_is_required_and_rejection_is_logged(tmp_path):
    execution, broker, history = service(tmp_path)

    result = execution.execute(spec(stop_price=0.0), portfolio(), international_deployed=0)

    assert not result.approved
    assert broker.orders == []
    assert "Explicit stop" in history.records()[0]["rejection_reason"]


def test_international_allocation_cap_prevents_submission(tmp_path):
    execution, broker, history = service(tmp_path)

    result = execution.execute(spec(), portfolio(), international_deployed=1000.0)

    assert not result.approved
    assert broker.orders == []
    assert "allocation cap" in history.records()[0]["rejection_reason"]


def test_approved_order_respects_risk_and_allocation_caps(tmp_path):
    policy = InternationalExecutionPolicy(max_risk_per_trade_pct=0.01, min_cash_reserve_pct=0.10)
    execution, broker, history = service(tmp_path, policy=policy)

    result = execution.execute(spec(requested_quantity=20.0), portfolio(), international_deployed=900.0)

    assert result.approved and result.submitted
    assert result.quantity == 1.0
    assert broker.orders[0].risk_approved
    assert broker.orders[0].stop_price == 95.0
    assert history.records()[0]["notional"] == 100.0


def test_model_cannot_configure_risk_above_global_limit():
    with pytest.raises(ValueError, match="global limit"):
        InternationalExecutionPolicy(max_risk_per_trade_pct=0.50)


def test_international_discovery_classifies_foreign_sessions():
    now = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    assert InternationalPaperTradingJob._venue_session("LSE_SETS", now) == "OPEN"
    assert InternationalPaperTradingJob._venue_session("ASX", now) == "CLOSED"


def test_executed_and_closed_trade_feeds_trade_history_and_learning(tmp_path):
    execution, _, history = service(tmp_path)
    opened = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    result = execution.execute(spec(), portfolio(), international_deployed=0, now=opened)
    assert result.trade_id is not None
    history.record_close(
        result.trade_id,
        exit_price=110.0,
        realized_pnl=20.0,
        fees_costs=1.0,
        final_outcome="win",
        now=opened + timedelta(hours=3),
    )

    record = history.learning_records()[0]
    assert record["fill_price"] == 100.1
    assert record["exit_price"] == 110.0
    assert record["realized_pnl"] == 20.0
    assert record["fees_costs"] == 1.25
    assert record["holding_period_seconds"] == 10800.0
    learner = RealizedOutcomeLearner(
        ledger_path=str(tmp_path / "ledger.db"),
        stats_path=str(tmp_path / "stats.json"),
        parameters_path=str(tmp_path / "parameters.json"),
        history_path=str(tmp_path / "learning.jsonl"),
    )
    learning = learner.update(opened + timedelta(hours=4))
    assert learning["completed_trades"] == 1
    assert learning["cumulative_realized_pnl"] == 18.75
    assert learning["hard_guardrails_mutable"] is False
