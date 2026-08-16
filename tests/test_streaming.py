from autotrader.streaming import normalize_alpaca_message, normalize_oanda_message


def test_normalize_alpaca_quote():
    event = normalize_alpaca_message(
        {
            "T": "q",
            "S": "AAPL",
            "bp": 200.1,
            "ap": 200.2,
            "bs": 10,
            "as": 12,
            "t": "2026-08-16T18:00:00.123456Z",
        }
    )
    assert event is not None
    assert event.provider == "alpaca"
    assert event.kind == "quote"
    assert event.symbol == "AAPL"
    assert event.bid == 200.1
    assert event.ask == 200.2


def test_normalize_oanda_price():
    event = normalize_oanda_message(
        {
            "type": "PRICE",
            "instrument": "EUR_USD",
            "time": "2026-08-16T18:00:00.123456Z",
            "bids": [{"price": "1.10001", "liquidity": 1000000}],
            "asks": [{"price": "1.10003", "liquidity": 900000}],
        }
    )
    assert event is not None
    assert event.provider == "oanda"
    assert event.symbol == "EUR/USD"
    assert event.bid == 1.10001
    assert event.ask == 1.10003
    assert event.bid_size == 1000000.0


def test_normalize_oanda_heartbeat():
    event = normalize_oanda_message(
        {"type": "HEARTBEAT", "time": "2026-08-16T18:00:00.123456Z"}
    )
    assert event is not None
    assert event.kind == "heartbeat"
    assert event.symbol is None
