from datetime import UTC, datetime, timedelta

from autotrader.brokers.alpaca_metals_paper import AlpacaMetalsOrderResult
from autotrader.learning import RealizedOutcomeLearner
from autotrader.metals_trading import (
    MetalsExecutionService,
    MetalsOrderSpec,
    MetalsTradeHistory,
)
from autotrader.models import AssetClass, PortfolioState, Position, Side, TradeProposal


class FakeMetalsBroker:
    def __init__(self, *, tradable=True):
        self.tradable = tradable
        self.checked = []
        self.orders = []

    def is_tradable(self, symbol):
        self.checked.append(symbol)
        return self.tradable

    def submit_order(self, order):
        self.orders.append(order)
        return AlpacaMetalsOrderResult(True, "paper-metals-1", "accepted", 100.25, 0.20)


def spec(**overrides):
    values = {
        "symbol": "GLD",
        "asset_class": AssetClass.ETF,
        "side": Side.BUY,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "confidence": 0.75,
        "source": "metals-model",
        "requested_quantity": 2.0,
    }
    values.update(overrides)
    return MetalsOrderSpec(TradeProposal(**values), target_price=110.0, strategy_version="metals-v1")


def portfolio(**overrides):
    values = {"equity": 5000.0, "cash": 5000.0}
    values.update(overrides)
    return PortfolioState(**values)


def service(tmp_path, *, tradable=True):
    broker = FakeMetalsBroker(tradable=tradable)
    history = MetalsTradeHistory(tmp_path / "ledger.db")
    return MetalsExecutionService(broker, history), broker, history


def test_risk_rejection_blocks_submission_and_logs_proposal(tmp_path):
    execution, broker, history = service(tmp_path)
    positions = {f"P{i}": Position(f"P{i}", AssetClass.STOCK, 1, 10, 9) for i in range(6)}

    result = execution.execute(spec(), portfolio(positions=positions), metals_deployed=0)

    assert not result.approved and not result.submitted
    assert broker.orders == []
    assert broker.checked == []
    record = history.records()[0]
    assert record["risk_decision"] == "rejected"
    assert "Maximum open positions" in record["rejection_reason"]


def test_explicit_stop_is_required_and_rejection_is_logged(tmp_path):
    execution, broker, history = service(tmp_path)

    result = execution.execute(spec(stop_price=0.0), portfolio(), metals_deployed=0)

    assert not result.approved
    assert broker.orders == []
    assert "Explicit stop" in history.records()[0]["rejection_reason"]


def test_untradable_symbol_is_filtered_before_submission_and_logged(tmp_path):
    execution, broker, history = service(tmp_path, tradable=False)

    result = execution.execute(spec(), portfolio(), metals_deployed=0)

    assert not result.approved
    assert broker.orders == []
    assert broker.checked == ["GLD"]
    assert "not currently active and tradable" in history.records()[0]["rejection_reason"]


def test_metals_allocation_is_hard_capped_at_one_thousand(tmp_path):
    execution, broker, history = service(tmp_path)

    result = execution.execute(spec(), portfolio(), metals_deployed=1000.0)

    assert not result.approved
    assert broker.orders == []
    assert "allocation cap" in history.records()[0]["rejection_reason"]


def test_approved_metals_order_uses_deterministic_sizing(tmp_path):
    execution, broker, history = service(tmp_path)

    result = execution.execute(spec(requested_quantity=20.0), portfolio(), metals_deployed=800.0)

    assert result.approved and result.submitted
    assert result.quantity == 2.0
    assert broker.orders[0].risk_approved
    assert broker.orders[0].stop_price == 95.0
    assert history.records()[0]["notional"] == 200.0


def test_completed_metals_trade_feeds_learning_history(tmp_path):
    execution, _, history = service(tmp_path)
    opened = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    result = execution.execute(spec(), portfolio(), metals_deployed=0, now=opened)
    assert result.trade_id is not None
    history.record_close(
        result.trade_id,
        exit_price=110.0,
        realized_pnl=20.0,
        fees_costs=0.80,
        final_outcome="win",
        now=opened + timedelta(hours=2),
    )

    record = history.learning_records()[0]
    assert record["holding_period_seconds"] == 7200.0
    assert record["fees_costs"] == 1.0
    learner = RealizedOutcomeLearner(
        ledger_path=str(tmp_path / "ledger.db"),
        stats_path=str(tmp_path / "stats.json"),
        parameters_path=str(tmp_path / "parameters.json"),
        history_path=str(tmp_path / "learning.jsonl"),
    )
    learning = learner.update(opened + timedelta(hours=3))
    assert learning["completed_trades"] == 1
    assert learning["cumulative_realized_pnl"] == 19.0
    assert learning["hard_guardrails_mutable"] is False
