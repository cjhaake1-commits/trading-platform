import pytest

from autotrader.brokers.alpaca_metals_paper import (
    ALPACA_PAPER_BASE_URL,
    METALS_UNIVERSE,
    AlpacaApprovedMetalsOrder,
    AlpacaMetalsConfigurationError,
    AlpacaMetalsPaperAdapter,
    AlpacaMetalsSafetyError,
)


def test_alpaca_live_environment_is_rejected():
    with pytest.raises(AlpacaMetalsConfigurationError, match="locked"):
        AlpacaMetalsPaperAdapter(environment="live", api_key="key", api_secret="secret")


def test_missing_paper_credentials_are_rejected(monkeypatch):
    monkeypatch.setenv("ALPACA_ENV", "paper")
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET_KEY", raising=False)

    with pytest.raises(AlpacaMetalsConfigurationError, match="Missing"):
        AlpacaMetalsPaperAdapter.from_env()


def test_tradability_filter_checks_each_supported_asset_dynamically():
    def fake_request(url, method, headers, body, timeout):
        assert method == "GET"
        symbol = url.rsplit("/", 1)[-1]
        return {"symbol": symbol, "status": "active", "tradable": symbol in {"GLD", "SLV", "GDX"}}, {}

    adapter = AlpacaMetalsPaperAdapter(
        environment="paper",
        api_key="key",
        api_secret="secret",
        request_json=fake_request,
    )

    assert set(adapter.tradable_metals()) == {"GLD", "SLV", "GDX"}
    assert set(METALS_UNIVERSE) == {"GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL"}


def test_order_requires_risk_approval_and_never_reaches_requester():
    calls = []

    def fake_request(*args):
        calls.append(args)
        return {}, {}

    adapter = AlpacaMetalsPaperAdapter(
        environment="paper",
        api_key="key",
        api_secret="secret",
        request_json=fake_request,
    )
    order = AlpacaApprovedMetalsOrder("GLD", "buy", 1, 300.0, 350.0, "test", False)

    with pytest.raises(AlpacaMetalsSafetyError, match="risk approval"):
        adapter.submit_order(order)
    assert calls == []


def test_approved_order_posts_bracket_only_to_alpaca_paper():
    captured = {}

    def fake_request(url, method, headers, body, timeout):
        captured.update(url=url, method=method, headers=headers, body=body, timeout=timeout)
        if method == "GET":
            return {"symbol": "GLD", "status": "active", "tradable": True}, {}
        return {"id": "paper-order-1", "filled_avg_price": "325.10"}, {}

    adapter = AlpacaMetalsPaperAdapter(
        environment="paper",
        api_key="key",
        api_secret="secret",
        request_json=fake_request,
    )
    result = adapter.submit_order(AlpacaApprovedMetalsOrder("GLD", "buy", 2, 310.0, 350.0, "metals-test", True))

    assert result.ok
    assert captured["url"] == f"{ALPACA_PAPER_BASE_URL}/v2/orders"
    assert captured["method"] == "POST"
    assert captured["body"]["order_class"] == "bracket"
    assert captured["body"]["stop_loss"] == {"stop_price": "310.00"}
    assert "key" not in str(result)
    assert "secret" not in str(result)
