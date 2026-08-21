from __future__ import annotations

import io
from urllib.error import HTTPError

import autotrader.brokers.practice_orders as practice_orders
import autotrader.brokers.safety as safety


class _FakeResponse:
    def __init__(self, payload: str, headers: dict[str, str] | None = None):
        self._payload = payload.encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_alpaca_request_retries_after_429_with_retry_after(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=15.0):
        calls.append(timeout)
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                429,
                "too many requests",
                {"Retry-After": "0"},
                io.BytesIO(b'{"code":42910000,"message":"rate limit exceeded"}'),
            )
        return _FakeResponse('{"ok": true}', {"X-Request-ID": "req-1"})

    sleeps = []
    monkeypatch.setattr(safety, "urlopen", fake_urlopen)
    monkeypatch.setattr(safety.time, "sleep", lambda seconds: sleeps.append(seconds))
    payload, headers = safety._request(
        "https://paper-api.alpaca.markets/v2/account",
        method="GET",
        headers={"Accept": "application/json"},
        retries=1,
    )

    assert payload == {"ok": True}
    assert headers["X-Request-ID"] == "req-1"
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_practice_order_request_retries_after_429(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=15.0):
        calls.append(timeout)
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                429,
                "too many requests",
                {"Retry-After": "0"},
                io.BytesIO(b'{"code":42910000,"message":"rate limit exceeded"}'),
            )
        return _FakeResponse('{"status": "ok"}', {"X-Request-ID": "req-2"})

    sleeps = []
    monkeypatch.setattr(practice_orders, "urlopen", fake_urlopen)
    monkeypatch.setattr(practice_orders.time, "sleep", lambda seconds: sleeps.append(seconds))
    payload, headers = practice_orders._request_json(
        "https://paper-api.alpaca.markets/v2/orders",
        method="GET",
        headers={"Accept": "application/json"},
        retries=1,
    )

    assert payload == {"status": "ok"}
    assert headers["X-Request-ID"] == "req-2"
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_broker_request_budget_caps_requests():
    budget = safety.BrokerRequestBudget(limit=2)
    budget.consume()
    budget.consume()
    try:
        budget.consume()
    except RuntimeError as exc:
        assert "budget exceeded" in str(exc).lower()
    else:
        raise AssertionError("expected request budget to fault after limit")
