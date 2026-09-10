from __future__ import annotations

from unittest.mock import Mock

import pytest

from autotrader.brokers import safety


def position(long="10", short="0"):
    return {"instrument": "EUR_USD", "long": {"units": long}, "short": {"units": short}}


def arrange(monkeypatch, snapshots):
    monkeypatch.setattr(safety, "_oanda_auth", lambda: ("test-token", "https://api-fxpractice.oanda.com", "test-account"))
    reader = Mock(side_effect=[
        safety.BrokerSafetyResult("oanda-practice", True, "test fixture", {"positions": rows})
        for rows in snapshots
    ])
    request = Mock(return_value=({"test_only_receipt": True}, {}))
    clear = Mock(return_value=True)
    monkeypatch.setattr(safety, "oanda_open_positions", reader)
    monkeypatch.setattr(safety, "_request", request)
    monkeypatch.setattr(safety, "_clear_flat_ledger_symbol", clear)
    return request, clear


@pytest.mark.parametrize(("row", "expected"), [
    (position(), {"longUnits": "ALL", "shortUnits": "NONE"}),
    (position("0", "-10"), {"longUnits": "NONE", "shortUnits": "ALL"}),
    (position("10", "-10"), {"longUnits": "ALL", "shortUnits": "ALL"}),
])
def test_close_only_provider_confirmed_sides(monkeypatch, row, expected):
    request, clear = arrange(monkeypatch, [[row], []])
    result = safety.close_oanda_position("EUR/USD", ledger_path="test-ledger.db")
    assert request.call_count == 1
    assert request.call_args.kwargs["body"] == expected
    assert request.call_args.kwargs["method"] == "PUT"
    assert request.call_args.args[0].startswith("https://api-fxpractice.oanda.com/")
    assert result.ok and result.details["submitted"] is True
    clear.assert_called_once_with("EUR/USD", "test-ledger.db")


def test_already_flat_reconciles_without_inventing_an_order(monkeypatch):
    request, clear = arrange(monkeypatch, [[]])
    result = safety.close_oanda_position("EUR/USD")
    request.assert_not_called()
    clear.assert_called_once()
    assert result.ok
    assert result.details["submitted"] is False
    assert result.details["result"] == {}


def test_unselected_side_is_not_closed(monkeypatch):
    request, clear = arrange(monkeypatch, [[position("10", "-5")], [position("10", "0")]])
    result = safety.close_oanda_position("EUR/USD", long_units=None)
    assert request.call_args.kwargs["body"] == {"longUnits": "NONE", "shortUnits": "ALL"}
    assert not result.ok
    clear.assert_not_called()


def test_zero_net_hedge_is_not_flat(monkeypatch):
    request, clear = arrange(monkeypatch, [[position("10", "-10")], [position("10", "-10")]])
    result = safety.close_oanda_position("EUR/USD")
    assert request.call_count == 1
    assert not result.ok
    assert result.details["position_still_open"] is True
    clear.assert_not_called()


@pytest.mark.parametrize("rows", [
    None, {}, [None], [{"instrument": "EUR_USD"}],
    [position("nan")], [position("inf")], [position("-10")],
    [position("0", "10")], [position(), position()],
])
def test_unverified_snapshot_cannot_submit_or_release_capital(monkeypatch, rows):
    request, clear = arrange(monkeypatch, [rows])
    with pytest.raises(RuntimeError):
        safety.close_oanda_position("EUR/USD")
    request.assert_not_called()
    clear.assert_not_called()


def test_failed_post_close_read_never_releases_capital(monkeypatch):
    request, clear = arrange(monkeypatch, [[position()], None])
    with pytest.raises(RuntimeError):
        safety.close_oanda_position("EUR/USD")
    assert request.call_count == 1
    clear.assert_not_called()


def test_provider_error_is_not_suppressed_or_retried(monkeypatch):
    request, clear = arrange(monkeypatch, [[position()]])
    request.side_effect = RuntimeError("HTTP 401: test fixture")
    with pytest.raises(RuntimeError, match="HTTP 401"):
        safety.close_oanda_position("EUR/USD")
    assert request.call_count == 1
    clear.assert_not_called()


def test_partial_close_preserves_requested_quantity(monkeypatch):
    request, clear = arrange(monkeypatch, [[position()], [position("7")]])
    result = safety.close_oanda_position("EUR/USD", long_units="3", short_units=None)
    assert request.call_args.kwargs["body"] == {"longUnits": "3", "shortUnits": "NONE"}
    assert not result.ok
    clear.assert_not_called()
