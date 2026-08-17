from autotrader.brokers import practice_orders


def test_oanda_protected_order_serialization(monkeypatch):
    captured = {}

    def fake_request(url, *, method, headers, body=None, timeout=15.0):
        captured.update(
            {
                "url": url,
                "method": method,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        return (
            {
                "orderCreateTransaction": {"id": "10"},
                "orderFillTransaction": {"id": "11"},
                "relatedTransactionIDs": ["10", "11"],
                "lastTransactionID": "11",
            },
            {"RequestID": "request-1"},
        )

    monkeypatch.setenv("OANDA_PRACTICE_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_PRACTICE_ACCOUNT_ID", "account-1")
    monkeypatch.setattr(practice_orders, "_request_json", fake_request)

    result = practice_orders.submit_oanda_practice_market_order(
        "EUR/USD",
        units=1,
        stop_price=1.075,
        client_order_id="safe-123",
    )

    assert result.ok
    assert captured["method"] == "POST"
    order = captured["body"]["order"]
    assert order["instrument"] == "EUR_USD"
    assert order["units"] == "1"
    assert order["stopLossOnFill"] == {"price": "1.075", "timeInForce": "GTC"}
    assert order["clientExtensions"]["id"] == "safe-123"
    assert order["tradeClientExtensions"]["id"] == "safe-123"
    assert "test-token" not in str(result.details)


def test_alpaca_oto_stop_serialization(monkeypatch):
    captured = {}

    def fake_request(url, *, method, headers, body=None, timeout=15.0):
        captured.update(
            {
                "url": url,
                "method": method,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        return (
            {
                "id": "order-1",
                "client_order_id": "safe-456",
                "symbol": "SPY",
                "status": "accepted",
            },
            {"X-Request-ID": "request-2"},
        )

    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "test-secret")
    monkeypatch.setattr(practice_orders, "_request_json", fake_request)

    result = practice_orders.submit_alpaca_paper_protected_order(
        "SPY",
        qty=0.01,
        stop_price=490.0,
        client_order_id="safe-456",
    )

    assert result.ok
    payload = captured["body"]
    assert payload["order_class"] == "oto"
    assert payload["stop_loss"] == {"stop_price": "490.00"}
    assert payload["client_order_id"] == "safe-456"
    assert "test-key" not in str(result.details)
    assert "test-secret" not in str(result.details)


def test_alpaca_oto_rounds_subpenny_stop(monkeypatch):
    captured = {}

    def fake_request(url, *, method, headers, body=None, timeout=15.0):
        captured["body"] = body
        return ({"id": "order-2", "status": "accepted", "symbol": "AVGO"}, {})

    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "test-secret")
    monkeypatch.setattr(practice_orders, "_request_json", fake_request)

    result = practice_orders.submit_alpaca_paper_protected_order(
        "AVGO",
        qty=3,
        stop_price=392.66891122,
    )

    assert result.ok
    assert captured["body"]["stop_loss"] == {"stop_price": "392.67"}
