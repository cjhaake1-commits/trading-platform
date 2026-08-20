from datetime import UTC, datetime, timedelta

import pytest

from autotrader.brokers.saxo_sim import SaxoOrderResult
from autotrader.international_trading import (
    InternationalExecutionPolicy,
    InternationalExecutionService,
    InternationalOrderSpec,
    InternationalTradeHistory,
)
from autotrader.learning import RealizedOutcomeLearner
from autotrader.models import AssetClass, PortfolioState, Position, Side, TradeProposal


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
