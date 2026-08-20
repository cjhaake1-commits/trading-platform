import pytest

from autotrader.brokers.saxo_sim import (
    SAXO_SIM_BASE_URL,
    SaxoApprovedOrder,
    SaxoConfigurationError,
    SaxoReadOnlyError,
    SaxoSimAdapter,
)


def test_sim_only_safety_lock():
    with pytest.raises(SaxoConfigurationError, match="locked"):
        SaxoSimAdapter(environment="live", access_token="secret")


def test_missing_token_handling(monkeypatch):
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)

    with pytest.raises(SaxoConfigurationError, match="Missing SAXO_ACCESS_TOKEN"):
        SaxoSimAdapter.from_env()


def test_international_allocation_is_capped_at_one_thousand():
    def fake_get(url, headers, timeout):
        assert url.startswith(SAXO_SIM_BASE_URL)
        assert headers["Authorization"] == "Bearer test-token"
        assert timeout == 10.0
        if url.endswith("/clients/me"):
            return (
                {
                    "ClientId": "client-safe",
                    "DefaultAccountId": "account-safe",
                    "DefaultCurrency": "USD",
                },
                {},
            )
        if url.endswith("/accounts/me"):
            return (
                {
                    "Data": [
                        {
                            "AccountId": "account-safe",
                            "Currency": "USD",
                            "Active": True,
                            "AccountType": "Normal",
                        }
                    ]
                },
                {},
            )
        return (
            {
                "Currency": "USD",
                "CashBalance": 100_000.0,
                "CashAvailableForTrading": 100_000.0,
                "TotalValue": 125_000.0,
            },
            {},
        )

    summary = SaxoSimAdapter(
        environment="sim",
        access_token="test-token",
        get_json=fake_get,
    ).account_summary()

    assert summary.total_value == 125_000.0
    assert summary.international_allocation_cap == 1_000.0
    assert "test-token" not in str(summary.as_dict())


def test_no_order_submission_in_read_only_mode():
    adapter = SaxoSimAdapter(environment="sim", access_token="test-token")

    with pytest.raises(SaxoReadOnlyError, match="risk approval"):
        adapter.submit_order(
            SaxoApprovedOrder(
                account_key="account",
                uic=1234,
                asset_type="Stock",
                side="buy",
                quantity=1,
                stop_price=90,
                external_reference="test",
                risk_approved=False,
            )
        )


def test_account_probe_uses_get_only():
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url.endswith("/accounts/me"):
            return {"Data": []}, {}
        return {}, {}

    SaxoSimAdapter(environment="sim", access_token="test-token", get_json=fake_get).account_summary()

    assert calls == [
        f"{SAXO_SIM_BASE_URL}/port/v1/clients/me",
        f"{SAXO_SIM_BASE_URL}/port/v1/accounts/me",
        f"{SAXO_SIM_BASE_URL}/port/v1/balances/me",
    ]


def test_risk_approved_order_posts_only_to_sim_with_protective_stop():
    captured = {}

    def fake_request(url, method, headers, body, timeout):
        captured.update(url=url, method=method, headers=headers, body=body, timeout=timeout)
        return {"OrderId": "sim-order-123", "Price": 100.25}, {}

    adapter = SaxoSimAdapter(
        environment="sim",
        access_token="test-token",
        request_json=fake_request,
    )
    result = adapter.submit_order(
        SaxoApprovedOrder(
            account_key="sim-account",
            uic=1234,
            asset_type="Stock",
            side="buy",
            quantity=2,
            stop_price=95.0,
            external_reference="risk-approved-1",
            risk_approved=True,
        )
    )

    assert result.ok
    assert captured["url"] == f"{SAXO_SIM_BASE_URL}/trade/v2/orders"
    assert captured["method"] == "POST"
    assert captured["body"]["OrderType"] == "Market"
    assert captured["body"]["Orders"][0]["OrderType"] == "Stop"
    assert captured["body"]["Orders"][0]["OrderPrice"] == 95.0
    assert "test-token" not in str(result)
