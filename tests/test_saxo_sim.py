import json
import time

import pytest

from autotrader.brokers.saxo_sim import (
    SAXO_SIM_BASE_URL,
    SaxoApprovedOrder,
    SaxoChartSample,
    SaxoConfigurationError,
    SaxoInstrumentSummary,
    SaxoReadOnlyError,
    SaxoSimAdapter,
    SaxoTokenStore,
)


def test_sim_only_safety_lock():
    with pytest.raises(SaxoConfigurationError, match="locked"):
        SaxoSimAdapter(environment="live", access_token="secret")


def test_missing_token_handling(monkeypatch, tmp_path):
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SAXO_TOKEN_STORE", str(tmp_path / "missing.json"))

    with pytest.raises(SaxoConfigurationError, match="Missing managed Saxo SIM OAuth token"):
        SaxoSimAdapter.from_env()


def test_from_env_ignores_static_access_token_without_managed_store(monkeypatch, tmp_path):
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "stale-static-token")
    monkeypatch.setenv("SAXO_TOKEN_STORE", str(tmp_path / "missing.json"))

    with pytest.raises(SaxoConfigurationError, match="Missing managed Saxo SIM OAuth token"):
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


def test_session_capabilities_are_read_from_authoritative_saxo_endpoint():
    def fake_get(url, headers, timeout):
        assert url == f"{SAXO_SIM_BASE_URL}/root/v1/sessions/capabilities"
        return {"AuthenticationLevel": "Authenticated", "DataLevel": "Standard", "TradeLevel": "OrdersOnly"}, {}

    result = SaxoSimAdapter(environment="sim", access_token="test-token", get_json=fake_get).session_capabilities()
    assert result["AuthenticationLevel"] == "Authenticated"
    assert result["TradeLevel"] == "OrdersOnly"


def test_risk_approved_order_posts_independent_entry_without_related_stop():
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
    assert "Orders" not in captured["body"]
    assert "test-token" not in str(result)


def test_saxo_precheck_and_execution_share_entry_payload_semantics():
    order = SaxoApprovedOrder("sim-account", 1234, "Stock", "buy", 2, 95.0, "same", True)
    expected = SaxoSimAdapter.build_entry_order_payload(order)
    captured = {}

    def fake_request(url, method, headers, body, timeout):
        captured["body"] = body
        return ({"OrderId": "sim-order-123"} if url.endswith("/orders") else {"PreCheckResult": "Ok"}), {}

    adapter = SaxoSimAdapter(environment="sim", access_token="test-token", request_json=fake_request)
    precheck = adapter.precheck_order(expected)
    result = adapter.submit_order(order)
    assert precheck["PreCheckResult"] == "Ok"
    assert result.ok
    assert {k: captured["body"][k] for k in expected} == expected
    assert "Orders" not in captured["body"]


def test_saxo_sim_mutation_lifecycle_is_guarded_to_sim():
    calls = []

    def fake_request(url, method, headers, body, timeout):
        calls.append((url, method, body))
        if method == "POST":
            return {"OrderId": "sim-1"}, {}
        return {}, {}

    adapter = SaxoSimAdapter(environment="sim", access_token="test-token", request_json=fake_request)
    result = adapter.close_position(
        account_key="account", position_id="position", uic=21, asset_type="FxSpot", amount=1, side="sell"
    )
    assert result.ok
    assert calls[0][0] == f"{SAXO_SIM_BASE_URL}/trade/v2/orders"
    assert calls[0][1] == "POST"
    assert calls[0][2]["PositionId"] == "position"

    adapter.cancel_order("sim-1", account_key="account")
    assert calls[1][0].startswith(f"{SAXO_SIM_BASE_URL}/trade/v2/orders/sim-1?")
    assert calls[1][1] == "DELETE"


def test_instrument_discovery_and_chart_reads_use_sim_get_only():
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if "/ref/v1/instruments?" in url:
            return {
                "Data": [
                    {
                        "Identifier": 123,
                        "AssetType": "Stock",
                        "Symbol": "SAP:xetr",
                        "Description": "SAP SE",
                        "ExchangeId": "XETR",
                    }
                ]
            }, {}
        return {
            "Data": [
                {
                    "Time": "2026-08-20T00:00:00Z",
                    "Open": 100.01,
                    "High": 100.0,
                    "Low": 99.0,
                    "Close": 99.5,
                    "Volume": 1000,
                    "MarketTradingState": "Closed",
                }
            ]
        }, {}

    adapter = SaxoSimAdapter(environment="sim", access_token="test-token", get_json=fake_get)
    instruments = adapter.search_instruments("SAP")
    samples = adapter.chart_samples(instruments[0])

    assert instruments == (SaxoInstrumentSummary(123, "Stock", "SAP:xetr", "SAP SE", "XETR", None),)
    assert samples == (SaxoChartSample("2026-08-20T00:00:00Z", 100.01, 100.01, 99.0, 99.5, 1000.0, "Closed"),)
    assert all(url.startswith(SAXO_SIM_BASE_URL) for url in calls)
    assert all("test-token" not in url for url in calls)


def test_saxo_read_boundary_rejects_unapproved_resources():
    adapter = SaxoSimAdapter(environment="sim", access_token="test-token")
    with pytest.raises(SaxoReadOnlyError, match="read-only"):
        adapter._read("/trade/v2/orders")


def test_oauth_store_rotates_refresh_token_and_retries_401(tmp_path):
    store = SaxoTokenStore(str(tmp_path / "saxo.json"))
    store.save({"access_token": "old", "refresh_token": "refresh-1", "expires_at": time.time() + 600})
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            raise RuntimeError("Saxo SIM HTTP 401: unauthorized")
        return {"ClientId": "safe"}, {}

    adapter = SaxoSimAdapter(
        environment="sim",
        token_store=store,
        refresh_callback=lambda: {"access_token": "new", "refresh_token": "refresh-2", "expires_in": 600},
        get_json=fake_get,
    )
    assert adapter._read("/port/v1/clients/me") == {"ClientId": "safe"}
    assert calls == ["Bearer old", "Bearer new"]
    saved = json.loads((tmp_path / "saxo.json").read_text())
    assert saved["access_token"] == "new"
    assert saved["refresh_token"] == "refresh-2"
    assert "new" not in str(adapter.token_health)


def test_failed_oauth_refresh_leaves_sanitized_auth_error(tmp_path):
    store = SaxoTokenStore(str(tmp_path / "saxo.json"))
    store.save({"access_token": "old", "refresh_token": "refresh-1", "expires_at": time.time() + 600})

    def fake_get(url, headers, timeout):
        raise RuntimeError("Saxo SIM HTTP 401: old-secret-not-reported")

    adapter = SaxoSimAdapter(
        environment="sim",
        token_store=store,
        refresh_callback=lambda: (_ for _ in ()).throw(RuntimeError("refresh failed")),
        get_json=fake_get,
    )
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        adapter._read("/port/v1/clients/me")
    assert "old-secret" not in str(error.value)
