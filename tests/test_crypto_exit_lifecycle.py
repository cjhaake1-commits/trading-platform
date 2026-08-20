import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import autotrader.autonomous_paper as autonomous_paper_module
import autotrader.brokers.alpaca_crypto_exit as alpaca_exit_module
import autotrader.order_test_app as order_test_app_module
from autotrader.autonomous_paper import AutonomousPaperConfig, AutonomousPaperTradingJob
from autotrader.brokers.alpaca_crypto_exit import AlpacaCryptoExitPaperBroker
from autotrader.cash_dashboard import aggregate_cash_dashboard
from autotrader.crypto_exit import (
    AlpacaCryptoExitCoordinator,
    CryptoOrderSnapshot,
    CryptoPositionSnapshot,
    canonical_crypto_symbol,
    managed_protective_orders,
    recover_unprotected_crypto_position,
)
from autotrader.execution_safety import IdempotencyStore
from autotrader.learning import RealizedOutcomeLearner
from autotrader.models import AssetClass, Instrument, MarketBar, PortfolioState, Position
from autotrader.portfolio_ledger import PortfolioLedger


class SimulatedAlpacaPaperCrypto:
    def __init__(
        self,
        *,
        quantity=1.0,
        average_price=100.0,
        fill_quantity=None,
        fill_price=110.0,
        cancel_failure=False,
        close_failure=False,
        protection_failure=False,
    ):
        self.quantity = quantity
        self.available = 0.0
        self.average_price = average_price
        self.fill_quantity = fill_quantity
        self.fill_price = fill_price
        self.cancel_failure = cancel_failure
        self.close_failure = close_failure
        self.protection_failure = protection_failure
        self.close_calls = []
        self.cancel_calls = []
        self.protection_calls = []
        self.orders = {
            "stop-1": CryptoOrderSnapshot(
                "stop-1",
                "BTC/USD",
                "sell",
                "stop_limit",
                "new",
                quantity,
                stop_price=90.0,
                client_order_id="recovery-BTCUSD-stop",
            )
        }

    def position(self, symbol):
        if self.quantity <= 1e-12:
            return None
        return CryptoPositionSnapshot(symbol, self.quantity, self.available, self.average_price)

    def open_orders(self, symbol):
        return tuple(
            order
            for order in self.orders.values()
            if order.symbol == symbol and order.status in {"new", "accepted", "partially_filled"}
        )

    def order(self, order_id):
        return self.orders[order_id]

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        if order_id == "stop-1" and self.cancel_failure:
            raise RuntimeError("simulated cancellation failure")
        old = self.orders[order_id]
        self.orders[order_id] = CryptoOrderSnapshot(
            old.order_id,
            old.symbol,
            old.side,
            old.order_type,
            "canceled",
            old.quantity,
            old.filled_quantity,
            old.filled_average_price,
            old.stop_price,
            old.client_order_id,
        )
        reserved = sum(
            order.quantity - order.filled_quantity
            for order in self.open_orders("BTC/USD")
            if order.side == "sell" and order.order_type in {"stop", "stop_limit", "trailing_stop"}
        )
        self.available = max(self.quantity - reserved, 0.0)

    def submit_close(self, symbol, quantity):
        self.close_calls.append(quantity)
        if quantity > self.quantity + 1e-12 or quantity > self.available + 1e-12:
            raise AssertionError("close exceeded available position")
        if self.close_failure:
            raise RuntimeError("simulated close failure")
        filled = quantity if self.fill_quantity is None else min(self.fill_quantity, quantity)
        self.quantity -= filled
        self.available = self.quantity
        status = "filled" if filled + 1e-12 >= quantity else "partially_filled"
        order = CryptoOrderSnapshot(
            "close-1",
            symbol,
            "sell",
            "market",
            status,
            quantity,
            filled,
            self.fill_price,
            client_order_id=None,
        )
        self.orders[order.order_id] = order
        return order

    def submit_protection(self, symbol, quantity, stop_price, client_order_id):
        self.protection_calls.append((quantity, stop_price, client_order_id))
        if self.protection_failure:
            raise RuntimeError("simulated protection failure")
        if quantity > self.available + 1e-12:
            raise RuntimeError("simulated quantity reservation conflict")
        order = CryptoOrderSnapshot(
            f"replacement-{len(self.protection_calls)}",
            symbol,
            "sell",
            "stop_limit",
            "new",
            quantity,
            stop_price=stop_price,
            client_order_id=client_order_id,
        )
        self.orders[order.order_id] = order
        self.available = max(self.quantity - quantity, 0.0)
        return order


def coordinator(tmp_path, broker, *, ledger_path=None):
    return AlpacaCryptoExitCoordinator(
        broker,
        IdempotencyStore(tmp_path / "idempotency.db"),
        ledger_path=str(ledger_path or tmp_path / "portfolio.db"),
        poll_attempts=2,
        poll_delay_seconds=0.0,
        sleeper=lambda _seconds: None,
    )


def test_full_btc_close_cancels_active_stop_before_close(tmp_path):
    broker = SimulatedAlpacaPaperCrypto()
    result = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0)

    assert result.ok
    assert broker.cancel_calls[0] == "stop-1"
    assert broker.close_calls == [1.0]
    assert result.remaining_quantity == 0.0
    assert result.replacement_protective_order_id is None


def test_partial_btc_close_replaces_stop_for_exact_residual(tmp_path):
    broker = SimulatedAlpacaPaperCrypto()
    result = coordinator(tmp_path, broker).close("BTC/USD", quantity=0.4, stop_price=90.0)

    assert result.ok
    assert broker.close_calls == [0.4]
    assert result.remaining_quantity == pytest.approx(0.6)
    assert broker.protection_calls[0][0] == pytest.approx(0.6)
    assert result.residual_protected


def test_stop_cancellation_failure_blocks_close_and_keeps_protection(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(cancel_failure=True)
    result = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0)

    assert not result.ok
    assert broker.close_calls == []
    assert result.residual_protected


def test_close_failure_after_stop_cancel_restores_protection(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(close_failure=True)
    result = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0)

    assert not result.ok
    assert broker.close_calls == [1.0]
    assert broker.protection_calls[0][0] == 1.0
    assert result.residual_protected


def test_failed_close_reports_unprotected_state_if_restoration_fails(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(close_failure=True, protection_failure=True)
    result = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0)

    assert not result.ok
    assert not result.residual_protected
    assert broker.close_calls == [1.0]


def test_persisted_exit_reservation_blocks_duplicate_after_restart(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(close_failure=True)
    first = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0)
    restarted = coordinator(tmp_path, broker)
    second = restarted.close("BTC/USD", stop_price=90.0)

    assert not first.ok
    assert second.duplicate_blocked
    assert second.residual_protected
    assert broker.close_calls == [1.0]


def test_completed_exit_expires_and_allows_later_new_position(tmp_path):
    started = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    broker = SimulatedAlpacaPaperCrypto()
    first = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0, now=started)
    assert first.ok

    broker.quantity = 1.0
    broker.available = 0.0
    broker.orders["stop-2"] = CryptoOrderSnapshot(
        "stop-2",
        "BTC/USD",
        "sell",
        "stop_limit",
        "new",
        1.0,
        stop_price=90.0,
        client_order_id="recovery-BTCUSD-new-position-stop",
    )
    second = coordinator(tmp_path, broker).close(
        "BTCUSD",
        stop_price=90.0,
        now=started + timedelta(seconds=901),
    )

    assert second.ok
    assert not second.duplicate_blocked
    assert broker.close_calls == [1.0, 1.0]


def test_failed_protected_exit_can_be_reevaluated_after_retry_cooldown(tmp_path):
    started = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    broker = SimulatedAlpacaPaperCrypto(close_failure=True)
    first = coordinator(tmp_path, broker).close("BTC/USD", stop_price=90.0, now=started)
    assert not first.ok
    assert first.residual_protected

    broker.close_failure = False
    second = coordinator(tmp_path, broker).close(
        "BTC/USD",
        stop_price=90.0,
        now=started + timedelta(seconds=61),
    )

    assert second.ok
    assert broker.close_calls == [1.0, 1.0]


def test_partial_exit_protection_is_rediscovered_after_restart(tmp_path):
    broker = SimulatedAlpacaPaperCrypto()
    result = coordinator(tmp_path, broker).close("BTC/USD", quantity=0.4, stop_price=90.0)
    assert result.ok

    coordinator(tmp_path, broker)  # new process object sharing only broker + SQLite state
    rediscovered = managed_protective_orders(broker, "BTCUSD")

    assert len(rediscovered) == 1
    assert rediscovered[0].order_id == result.replacement_protective_order_id
    assert rediscovered[0].quantity == pytest.approx(broker.quantity)
    assert broker.available == 0.0


def test_crypto_symbol_canonicalization_is_stable_across_restart():
    assert canonical_crypto_symbol("BTCUSD") == "BTC/USD"
    assert canonical_crypto_symbol("BTC/USD") == "BTC/USD"
    assert canonical_crypto_symbol("btc_usd") == "BTC/USD"


def test_terminal_idempotency_records_expire_and_are_cleaned(tmp_path):
    started = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    store = IdempotencyStore(tmp_path / "idempotency.db")
    key = store.make_key(
        broker="alpaca-crypto-paper",
        symbol="BTC/USD",
        side="sell",
        intent="exit",
        quantity=1.0,
    )
    assert store.reserve(
        key,
        broker="alpaca-crypto-paper",
        symbol="BTC/USD",
        side="sell",
        intent="exit",
        now=started,
    )
    store.mark_terminal(key, "completed", ttl_seconds=10, now=started)

    with sqlite3.connect(store.path) as connection:
        status = connection.execute(
            "SELECT status FROM order_intents WHERE idempotency_key = ?", (key,)
        ).fetchone()[0]
    assert status == "completed"
    assert store.cleanup_expired(now=started + timedelta(seconds=11)) == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 0


def test_close_quantity_cannot_exceed_position(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(quantity=0.5)
    with pytest.raises(ValueError, match="cannot exceed"):
        coordinator(tmp_path, broker).close("BTC/USD", quantity=0.6, stop_price=90.0)
    assert broker.cancel_calls == []
    assert broker.close_calls == []


def test_unmanaged_order_is_never_canceled(tmp_path):
    broker = SimulatedAlpacaPaperCrypto()
    broker.orders["manual-stop"] = CryptoOrderSnapshot(
        "manual-stop",
        "BTC/USD",
        "sell",
        "stop_limit",
        "new",
        1.0,
        stop_price=80.0,
        client_order_id="manual-protection",
    )
    coordinator(tmp_path, broker)  # original process exits before the lifecycle begins
    result = coordinator(tmp_path, broker).close("BTCUSD", stop_price=90.0)

    assert not result.ok
    assert broker.cancel_calls == ["stop-1"]
    assert broker.close_calls == []


def test_partial_fill_cancels_remainder_and_protects_actual_residual(tmp_path):
    broker = SimulatedAlpacaPaperCrypto(fill_quantity=0.25)
    result = coordinator(tmp_path, broker).close("BTC/USD", quantity=0.5, stop_price=90.0)

    assert not result.ok
    assert result.filled_quantity == 0.25
    assert result.remaining_quantity == 0.75
    assert "close-1" in broker.cancel_calls
    assert broker.protection_calls[-1][0] == 0.75
    assert result.residual_protected


def test_live_alpaca_endpoint_is_rejected(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://api.alpaca.markets")

    with pytest.raises(RuntimeError, match="Alpaca PAPER"):
        AlpacaCryptoExitPaperBroker.from_env()

    with pytest.raises(RuntimeError, match="Alpaca PAPER"):
        AlpacaCryptoExitPaperBroker("key", "secret", "https://api.alpaca.markets")


def test_crypto_open_order_discovery_avoids_server_symbol_mismatch(monkeypatch):
    captured = {}

    def fake_request(url, *, method, headers, body=None, timeout=15.0):
        captured.update(url=url, method=method)
        return [
            {
                "id": "btc-stop",
                "symbol": "BTC/USD",
                "side": "sell",
                "type": "stop_limit",
                "status": "new",
                "qty": "1",
                "filled_qty": "0",
                "client_order_id": "recovery-BTCUSD-stop",
            },
            {
                "id": "eth-stop",
                "symbol": "ETH/USD",
                "side": "sell",
                "type": "stop_limit",
                "status": "new",
                "qty": "1",
                "filled_qty": "0",
                "client_order_id": "recovery-ETHUSD-stop",
            },
        ], {}

    monkeypatch.setattr(alpaca_exit_module, "_request", fake_request)
    broker = AlpacaCryptoExitPaperBroker("key", "secret", "https://paper-api.alpaca.markets")
    orders = broker.open_orders("BTC/USD")

    assert captured["method"] == "GET"
    assert "symbols=" not in captured["url"]
    assert [order.order_id for order in orders] == ["btc-stop"]


def test_successful_exit_updates_history_cash_accounting_and_learning(tmp_path):
    ledger_path = tmp_path / "portfolio.db"
    ledger = PortfolioLedger(ledger_path)
    ledger.save_portfolio(
        PortfolioState(
            equity=5000.0,
            cash=4000.0,
            positions={"BTC/USD": Position("BTC/USD", AssetClass.CRYPTO, 1.0, 100.0, 90.0)},
        ),
        peak_equity=5000.0,
    )
    broker = SimulatedAlpacaPaperCrypto(fill_price=110.0)
    result = coordinator(tmp_path, broker, ledger_path=ledger_path).close(
        "BTC/USD",
        stop_price=90.0,
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.ok
    assert result.realized_pnl == 10.0
    portfolio, _peak = ledger.load_portfolio()
    assert "BTC/USD" not in portfolio.positions
    assert portfolio.cash == 4010.0
    assert portfolio.equity == 5010.0

    with sqlite3.connect(ledger_path) as connection:
        connection.row_factory = sqlite3.Row
        fills = [dict(row) for row in connection.execute("SELECT * FROM fills")]
    metadata = json.loads(fills[0]["metadata_json"])
    assert metadata["model_version"] == "five_pillar_baseline_v1"
    cash = aggregate_cash_dashboard(
        realized_records=fills,
        positions=[],
        available_cash=4010.0,
        original_capital=5000.0,
    )
    assert cash.net_trading_cash_generated == 10.0
    assert cash.realized_return == 0.002

    learning = RealizedOutcomeLearner(
        ledger_path=str(ledger_path),
        stats_path=str(tmp_path / "stats.json"),
        parameters_path=str(tmp_path / "params.json"),
        history_path=str(tmp_path / "learning.jsonl"),
    ).update(datetime(2026, 8, 20, tzinfo=UTC))
    assert learning["completed_trades"] == 1
    assert learning["cumulative_realized_pnl"] == 10.0


def test_recovery_refuses_to_invent_a_stop(tmp_path):
    class NoStopBroker:
        def position(self, symbol):
            return CryptoPositionSnapshot(symbol, 0.425654496, 0.0, 2345.3)

        def open_orders(self, symbol):
            return ()

        def order(self, order_id):
            raise AssertionError("should not call order when stop is missing")

        def cancel_order(self, order_id):
            raise AssertionError("should not cancel")

        def submit_close(self, symbol, quantity):
            raise AssertionError("should not close")

        def submit_protection(self, symbol, quantity, stop_price, client_order_id):
            raise AssertionError("should not protect")

    result = recover_unprotected_crypto_position(
        NoStopBroker(),
        ledger_path=str(tmp_path / "portfolio.db"),
        symbol="ETHUSD",
    )

    assert not result.ok
    assert result.state == "manual_review_required"


def test_recovery_uses_persisted_stop_and_broker_quantity(tmp_path):
    class RecoveryBroker:
        def __init__(self):
            self.protection_calls = []
            self.orders = {
                "rec-1": CryptoOrderSnapshot(
                    "rec-1",
                    "ETH/USD",
                    "sell",
                    "stop_limit",
                    "new",
                    0.425654496,
                    stop_price=2300.0,
                    client_order_id="recovery-ETHUSD-stop",
                )
            }

        def position(self, symbol):
            return CryptoPositionSnapshot(symbol, 0.425654496, 0.0, 2345.3)

        def open_orders(self, symbol):
            return tuple(self.orders.values())

        def order(self, order_id):
            return self.orders[order_id]

        def cancel_order(self, order_id):
            raise AssertionError("not expected")

        def submit_close(self, symbol, quantity):
            raise AssertionError("not expected")

        def submit_protection(self, symbol, quantity, stop_price, client_order_id):
            self.protection_calls.append((symbol, quantity, stop_price, client_order_id))
            return self.orders["rec-1"]

    broker = RecoveryBroker()
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.save_crypto_entry_state(
        "ETH/USD",
        broker="alpaca-paper",
        lifecycle_state="unprotected_position",
        requested_quantity=0.4267213,
        submitted_quantity=0.4267213,
        broker_filled_quantity=0.425654496,
        broker_position_quantity=0.425654496,
        reconciliation_difference=0.001066804,
        reconciliation_tolerance=0.005,
        reconciliation_status="fractional_reconciliation",
        protection_state="failed",
        protection_quantity=None,
        stop_price=2300.0,
        fill_price=2345.3,
        client_order_id="auto-ETH",
        entry_order_id="entry-1",
    )

    result = recover_unprotected_crypto_position(broker, ledger_path=str(tmp_path / "portfolio.db"), symbol="ETH/USD")

    assert result.ok
    assert result.stop_price == 2300.0
    assert result.protection_quantity == pytest.approx(0.425654496)
    assert broker.protection_calls[0][1] == pytest.approx(0.425654496)


def test_sync_accepts_bounded_fractional_crypto_difference(monkeypatch, tmp_path):
    responses = iter(
        [
            {"positions": [{"symbol": "ETH/USD", "qty": "0.425654496", "avg_entry_price": "2345.3", "side": "long"}]},
        ]
    )

    def fake_alpaca_open_positions():
        payload = next(responses)

        class Result:
            ok = True
            broker = "alpaca-paper"
            message = "ok"
            details = payload

        return Result()

    monkeypatch.setattr(order_test_app_module, "alpaca_open_positions", fake_alpaca_open_positions)

    sync = order_test_app_module._sync_submitted_position(
        broker="alpaca",
        symbol="ETH/USD",
        stop_price=2300.0,
        ledger_path=str(tmp_path / "portfolio.db"),
        initial_equity=5000.0,
        expected_quantity=0.4267213,
        asset_class=AssetClass.CRYPTO,
        attempts=1,
        delay_seconds=0.0,
    )

    assert sync["quantity"] == pytest.approx(0.425654496)
    assert sync["requested_quantity"] == pytest.approx(0.4267213)
    assert sync["reconciliation_status"] == "fractional_reconciliation"
    assert sync["reconciliation_difference"] == pytest.approx(0.001066804)


def test_sync_rejects_material_crypto_quantity_mismatch(monkeypatch, tmp_path):
    def fake_alpaca_open_positions():
        class Result:
            ok = True
            broker = "alpaca-paper"
            message = "ok"
            details = {"positions": [{"symbol": "ETH/USD", "qty": "0.2", "avg_entry_price": "2345.3", "side": "long"}]}

        return Result()

    monkeypatch.setattr(order_test_app_module, "alpaca_open_positions", fake_alpaca_open_positions)

    with pytest.raises(RuntimeError, match="only reached"):
        order_test_app_module._sync_submitted_position(
            broker="alpaca",
            symbol="ETH/USD",
            stop_price=2300.0,
            ledger_path=str(tmp_path / "portfolio.db"),
            initial_equity=5000.0,
            expected_quantity=0.4267213,
            asset_class=AssetClass.CRYPTO,
            attempts=1,
            delay_seconds=0.0,
        )


def test_autonomous_take_profit_routes_crypto_through_guarded_coordinator(monkeypatch, tmp_path):
    calls = []

    class FakeResult:
        ok = True
        message = "guarded crypto close"

    class FakeCoordinator:
        def __init__(self, broker, idempotency, *, ledger_path):
            calls.append((broker, idempotency, ledger_path))

        def close(self, symbol, *, stop_price):
            calls.append((symbol, stop_price))
            return FakeResult()

    monkeypatch.setattr(autonomous_paper_module, "AlpacaCryptoExitCoordinator", FakeCoordinator)
    monkeypatch.setattr(
        autonomous_paper_module.AlpacaCryptoExitPaperBroker,
        "from_env",
        classmethod(lambda cls: "paper-broker"),
    )
    monkeypatch.setattr(
        autonomous_paper_module,
        "close_alpaca_position",
        lambda *args, **kwargs: pytest.fail("generic close must not handle crypto take profits"),
    )
    job = AutonomousPaperTradingJob(
        AutonomousPaperConfig(
            ledger_path=str(tmp_path / "portfolio.db"),
            idempotency_path=str(tmp_path / "idempotency.db"),
        )
    )
    instrument = Instrument("BTC/USD", AssetClass.CRYPTO)
    position = Position("BTC/USD", AssetClass.CRYPTO, 1.0, 100.0, 90.0)
    bars = [
        MarketBar(
            "BTC/USD",
            AssetClass.CRYPTO,
            datetime(2026, 8, 20, tzinfo=UTC),
            115.0,
            116.0,
            114.0,
            115.0,
            1000.0,
        )
    ]

    exits = job._manage_take_profits(
        PortfolioState(5000.0, 4000.0, positions={"BTC/USD": position}),
        {instrument: bars},
    )

    assert exits[0]["message"] == "guarded crypto close"
    assert calls[-1] == ("BTC/USD", 90.0)
