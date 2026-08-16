from autotrader.broker_events import normalize_alpaca_trade_update, normalize_oanda_transaction
from autotrader.correlation_risk import CorrelationBucketEngine, CorrelationBucketPolicy
from autotrader.economic_events import EventRiskAssessment
from autotrader.models import AssetClass, PortfolioState, Position, Side, TradeProposal
from autotrader.news_streaming import normalize_alpaca_news
from autotrader.risk import RiskEngine
from autotrader.risk_stack import LayeredRiskStack, RiskStackPolicy


def proposal(symbol: str = "QQQ") -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        asset_class=AssetClass.ETF,
        side=Side.BUY,
        entry_price=100.0,
        stop_price=98.0,
        confidence=0.8,
        source="test",
    )


def test_event_window_can_block_new_entry():
    stack = LayeredRiskStack(RiskEngine())
    decision = stack.evaluate(
        proposal(),
        PortfolioState(equity=1000.0, cash=1000.0),
        event_risk=EventRiskAssessment(True, 0.50, True, ("CPI",), "scheduled event"),
    )
    assert not decision.approved
    assert decision.reason == "scheduled event"


def test_open_risk_budget_caps_new_quantity():
    portfolio = PortfolioState(
        equity=1000.0,
        cash=800.0,
        positions={"SPY": Position("SPY", AssetClass.ETF, 2.0, 100.0, 98.0)},
    )
    correlation = CorrelationBucketEngine(
        {"SPY": "beta", "QQQ": "beta"},
        policy=CorrelationBucketPolicy(
            max_bucket_notional_pct=2.0,
            soft_bucket_notional_pct=1.5,
            soft_risk_scale=1.0,
        ),
    )
    stack = LayeredRiskStack(
        RiskEngine(),
        correlation_engine=correlation,
        policy=RiskStackPolicy(max_portfolio_open_risk_pct=0.01),
    )
    decision = stack.evaluate(proposal(), portfolio, mark_prices={"SPY": 100.0})
    assert decision.approved
    assert decision.max_loss_dollars <= 6.0 + 1e-9


def test_normalize_alpaca_trade_fill():
    event = normalize_alpaca_trade_update(
        {
            "stream": "trade_updates",
            "data": {
                "event": "fill",
                "timestamp": "2026-08-16T20:00:00Z",
                "qty": "1",
                "price": "100.5",
                "order": {
                    "id": "o1",
                    "client_order_id": "c1",
                    "symbol": "SPY",
                    "side": "buy",
                    "status": "filled",
                },
            },
        }
    )
    assert event is not None
    assert event.event_type == "fill"
    assert event.client_order_id == "c1"
    assert event.price == 100.5


def test_normalize_oanda_fill():
    event = normalize_oanda_transaction(
        {
            "type": "ORDER_FILL",
            "time": "2026-08-16T20:00:00Z",
            "orderID": "42",
            "instrument": "EUR_USD",
            "units": "1",
            "price": "1.10",
        }
    )
    assert event is not None
    assert event.symbol == "EUR/USD"
    assert event.side == "buy"
    assert event.quantity == 1.0


def test_normalize_alpaca_news():
    event = normalize_alpaca_news(
        {
            "T": "n",
            "id": 7,
            "headline": "Example",
            "summary": "Summary",
            "symbols": ["SPY"],
            "created_at": "2026-08-16T20:00:00Z",
            "author": "Desk",
        }
    )
    assert event is not None
    assert event.symbols == ("SPY",)
    assert event.headline == "Example"
