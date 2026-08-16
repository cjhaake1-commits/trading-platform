from autotrader.models import (
    AssetClass,
    PortfolioState,
    Position,
    Side,
    TradeIntent,
    TradeProposal,
)
from autotrader.risk import RiskEngine


def proposal(**overrides):
    data = {
        "symbol": "NVDA",
        "asset_class": AssetClass.STOCK,
        "side": Side.BUY,
        "entry_price": 100.0,
        "stop_price": 98.0,
        "confidence": 0.7,
        "source": "test",
    }
    data.update(overrides)
    return TradeProposal(**data)


def portfolio(**overrides):
    data = {"equity": 1000.0, "cash": 1000.0}
    data.update(overrides)
    return PortfolioState(**data)


def test_sizes_trade_to_half_percent_risk():
    decision = RiskEngine().evaluate(proposal(), portfolio())
    assert decision.approved
    assert decision.max_loss_dollars <= 5.0 + 1e-9
    assert decision.quantity == 2.5


def test_rejects_short_selling_by_default():
    decision = RiskEngine().evaluate(
        proposal(side=Side.SELL, entry_price=100.0, stop_price=102.0),
        portfolio(),
    )
    assert not decision.approved
    assert "Short selling" in decision.reason


def test_rejects_after_daily_loss_limit():
    decision = RiskEngine().evaluate(proposal(), portfolio(daily_pnl=-20.0))
    assert not decision.approved
    assert "Daily loss" in decision.reason


def test_rejects_bad_long_stop():
    decision = RiskEngine().evaluate(proposal(stop_price=101.0), portfolio())
    assert not decision.approved
    assert "Long trade stop" in decision.reason


def test_exit_long_is_allowed_even_when_short_selling_disabled():
    state = portfolio(
        cash=500.0,
        positions={
            "NVDA": Position("NVDA", AssetClass.STOCK, 2.0, 100.0, 98.0),
        },
    )
    decision = RiskEngine().evaluate(
        proposal(
            side=Side.SELL,
            intent=TradeIntent.EXIT,
            entry_price=105.0,
            stop_price=104.0,
        ),
        state,
    )
    assert decision.approved
    assert decision.quantity == 2.0
    assert decision.max_loss_dollars == 0.0


def test_reduce_caps_quantity_to_existing_position():
    state = portfolio(
        positions={
            "NVDA": Position("NVDA", AssetClass.STOCK, 2.0, 100.0, 98.0),
        }
    )
    decision = RiskEngine().evaluate(
        proposal(
            side=Side.SELL,
            intent=TradeIntent.REDUCE,
            requested_quantity=10.0,
            entry_price=101.0,
            stop_price=100.0,
        ),
        state,
    )
    assert decision.approved
    assert decision.quantity == 2.0
