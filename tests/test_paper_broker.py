from autotrader.brokers.paper import PaperBroker
from autotrader.models import (
    AssetClass,
    PortfolioState,
    RiskDecision,
    Side,
    TradeIntent,
    TradeProposal,
)


def proposal(*, side, price, intent, quantity=None):
    return TradeProposal(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        side=side,
        entry_price=price,
        stop_price=price - 1.0 if side is Side.BUY else price + 1.0,
        confidence=0.8,
        source="test",
        intent=intent,
        requested_quantity=quantity,
    )


def test_enter_increase_reduce_exit_updates_cash_and_realized_pnl():
    portfolio = PortfolioState(equity=1000.0, cash=1000.0)
    broker = PaperBroker(portfolio)

    broker.execute(
        proposal(side=Side.BUY, price=100.0, intent=TradeIntent.ENTER),
        RiskDecision(True, "ok", quantity=2.0),
    )
    assert portfolio.cash == 800.0
    assert portfolio.positions["SPY"].quantity == 2.0

    broker.execute(
        proposal(side=Side.BUY, price=110.0, intent=TradeIntent.INCREASE),
        RiskDecision(True, "ok", quantity=2.0),
    )
    position = portfolio.positions["SPY"]
    assert position.quantity == 4.0
    assert position.average_price == 105.0
    assert portfolio.cash == 580.0

    fill = broker.execute(
        proposal(side=Side.SELL, price=115.0, intent=TradeIntent.REDUCE, quantity=1.0),
        RiskDecision(True, "ok", quantity=1.0),
    )
    assert fill["realized_pnl"] == 10.0
    assert portfolio.cash == 695.0
    assert portfolio.daily_pnl == 10.0
    assert portfolio.positions["SPY"].quantity == 3.0

    fill = broker.execute(
        proposal(side=Side.SELL, price=95.0, intent=TradeIntent.EXIT),
        RiskDecision(True, "ok", quantity=3.0),
    )
    assert fill["realized_pnl"] == -30.0
    assert portfolio.daily_pnl == -20.0
    assert portfolio.cash == 980.0
    assert "SPY" not in portfolio.positions
