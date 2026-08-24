from decimal import Decimal

from autotrader.brokers import practice_orders


def test_crypto_rules_preserve_provider_minimum_and_precision(monkeypatch):
    monkeypatch.setattr(practice_orders, "_alpaca_credentials", lambda: ("k", "s", "https://paper"))
    monkeypatch.setattr(
        practice_orders,
        "_request_json",
        lambda *args, **kwargs: (
            {
                "symbol": "BTC/USD",
                "status": "active",
                "tradable": True,
                "min_order_size": "0.000013",
                "min_trade_increment": "0.000000001",
                "price_increment": "0.000000001",
            },
            {},
        ),
    )
    rules = practice_orders.alpaca_crypto_trading_rules("BTC/USD")
    assert rules.tradable
    assert rules.min_order_size == Decimal("0.000013")
    quantity, reason = practice_orders.crypto_quantity_for_notional("BTC/USD", 100_000, 1)
    assert reason is None
    assert quantity == Decimal("0.000013")


def test_crypto_rules_do_not_invent_missing_provider_minimum(monkeypatch):
    monkeypatch.setattr(practice_orders, "_alpaca_credentials", lambda: ("k", "s", "https://paper"))
    monkeypatch.setattr(
        practice_orders,
        "_request_json",
        lambda *args, **kwargs: ({"symbol": "BTC/USD", "status": "active", "tradable": True}, {}),
    )
    quantity, reason = practice_orders.crypto_quantity_for_notional("BTC/USD", 100_000, 1)
    assert quantity is None
    assert reason == "PROVIDER_MINIMUM_UNAVAILABLE"
