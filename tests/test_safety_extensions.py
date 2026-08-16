from datetime import UTC, datetime, timedelta

from autotrader.correlation_risk import CorrelationBucketEngine, CorrelationBucketPolicy
from autotrader.economic_events import (
    EconomicEvent,
    EconomicEventRiskEngine,
    EventRiskPolicy,
    EventSeverity,
)
from autotrader.execution_safety import ExecutionReadinessGate, IdempotencyStore
from autotrader.models import AssetClass, MarketBar, PortfolioState, Position, Side, TradeProposal
from autotrader.open_risk import portfolio_open_risk
from autotrader.portfolio_ledger import PortfolioLedger
from autotrader.reconciliation import BrokerPosition, PositionReconciler
from autotrader.technical_features import atr, realized_volatility, rsi


def bars(count: int = 30) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    output = []
    price = 100.0
    for index in range(count):
        close = price + index * 0.5
        output.append(
            MarketBar(
                symbol="SPY",
                asset_class=AssetClass.ETF,
                timestamp=start + timedelta(days=index),
                open=close - 0.2,
                high=close + 0.8,
                low=close - 0.8,
                close=close,
                volume=1_000_000,
            )
        )
    return output


def test_technical_features_are_available_after_warmup():
    sample = bars()
    assert rsi(sample, 14) is not None
    assert atr(sample, 14) is not None
    assert realized_volatility(sample, 20) is not None


def test_high_impact_event_blocks_entries_at_release():
    now = datetime(2026, 8, 17, 12, 30, tzinfo=UTC)
    event = EconomicEvent(
        "cpi",
        "US CPI",
        now,
        EventSeverity.HIGH,
        currencies=("USD",),
    )
    engine = EconomicEventRiskEngine(EventRiskPolicy(block_new_entries_seconds=30))
    assessment = engine.assess([event], now=now, symbol="EUR/USD")
    assert assessment.affected
    assert assessment.block_new_entries
    assert assessment.risk_scale < 1.0


def test_ledger_survives_restart_and_deduplicates_fills(tmp_path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    state = PortfolioState(
        equity=1010.0,
        cash=810.0,
        daily_pnl=10.0,
        positions={
            "SPY": Position(
                "SPY",
                AssetClass.ETF,
                2.0,
                100.0,
                98.0,
                opened_at=datetime(2026, 8, 16, tzinfo=UTC),
            )
        },
    )
    ledger.save_portfolio(state, peak_equity=1020.0)
    assert ledger.record_fill(
        fill_key="alpaca:fill-1",
        broker="alpaca-paper",
        order_id="order-1",
        symbol="SPY",
        side="buy",
        quantity=2.0,
        price=100.0,
    )
    assert not ledger.record_fill(
        fill_key="alpaca:fill-1",
        broker="alpaca-paper",
        order_id="order-1",
        symbol="SPY",
        side="buy",
        quantity=2.0,
        price=100.0,
    )
    loaded = PortfolioLedger(tmp_path / "portfolio.db").load_portfolio()
    assert loaded is not None
    restored, peak = loaded
    assert restored.positions["SPY"].quantity == 2.0
    assert peak == 1020.0


def test_correlation_bucket_blocks_hidden_concentration():
    portfolio = PortfolioState(
        equity=1000.0,
        cash=500.0,
        positions={"SPY": Position("SPY", AssetClass.ETF, 3.0, 100.0, 98.0)},
    )
    engine = CorrelationBucketEngine(
        {"SPY": "beta", "QQQ": "beta"},
        CorrelationBucketPolicy(max_bucket_notional_pct=0.50, soft_bucket_notional_pct=0.40),
    )
    proposal = TradeProposal("QQQ", AssetClass.ETF, Side.BUY, 100.0, 98.0, 0.8, "test")
    assessment = engine.assess(proposal, portfolio, proposed_quantity=3.0)
    assert assessment.blocked


def test_open_risk_uses_stop_distance():
    portfolio = PortfolioState(
        equity=1000.0,
        cash=800.0,
        positions={"SPY": Position("SPY", AssetClass.ETF, 2.0, 100.0, 98.0)},
    )
    result = portfolio_open_risk(portfolio, mark_prices={"SPY": 101.0})
    assert result.total_open_risk_dollars == 6.0
    assert result.positions[0].unrealized_pnl == 2.0


def test_reconciliation_fails_closed_on_quantity_mismatch():
    portfolio = PortfolioState(
        equity=1000.0,
        cash=800.0,
        positions={"SPY": Position("SPY", AssetClass.ETF, 2.0, 100.0, 98.0)},
    )
    result = PositionReconciler().reconcile(
        portfolio,
        [BrokerPosition("alpaca-paper", "SPY", 1.0)],
    )
    assert not result.ok
    assert result.issues[0].kind == "quantity_mismatch"


def test_idempotency_survives_restart(tmp_path):
    path = tmp_path / "orders.db"
    first = IdempotencyStore(path)
    key = first.make_key(
        broker="oanda-practice",
        symbol="EUR/USD",
        side="buy",
        intent="enter",
        quantity=1,
        strategy_id="s1",
        decision_bucket="2026-08-16T21:05",
    )
    assert first.reserve(
        key,
        broker="oanda-practice",
        symbol="EUR/USD",
        side="buy",
        intent="enter",
    )
    second = IdempotencyStore(path)
    assert not second.reserve(
        key,
        broker="oanda-practice",
        symbol="EUR/USD",
        side="buy",
        intent="enter",
    )


def test_readiness_gate_fails_closed():
    result = ExecutionReadinessGate.evaluate(
        feed_ok=True,
        broker_ok=True,
        ledger_ok=False,
        risk_ok=True,
        duplicate_ok=True,
    )
    assert not result.ready
    assert "ledger" in result.reason
