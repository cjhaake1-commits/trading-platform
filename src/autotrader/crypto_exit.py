from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol

from .execution_safety import IdempotencyStore
from .portfolio_ledger import PortfolioLedger

TERMINAL_ORDER_STATUSES = {"canceled", "expired", "filled", "rejected"}
OPEN_ORDER_STATUSES = {"accepted", "calculated", "held", "new", "partially_filled", "pending_new"}
MANAGED_PROTECTION_PREFIXES = ("auto-", "recovery-")
COMPLETED_EXIT_TTL_SECONDS = 900
PROTECTED_FAILURE_RETRY_SECONDS = 60
UNPROTECTED_FAILURE_TTL_SECONDS = 900


@dataclass(frozen=True)
class CryptoPositionSnapshot:
    symbol: str
    quantity: float
    available_quantity: float
    average_price: float


@dataclass(frozen=True)
class CryptoOrderSnapshot:
    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    filled_quantity: float = 0.0
    filled_average_price: float | None = None
    stop_price: float | None = None
    client_order_id: str | None = None


class CryptoExitPaperBroker(Protocol):
    def position(self, symbol: str) -> CryptoPositionSnapshot | None: ...

    def open_orders(self, symbol: str) -> tuple[CryptoOrderSnapshot, ...]: ...

    def order(self, order_id: str) -> CryptoOrderSnapshot: ...

    def cancel_order(self, order_id: str) -> None: ...

    def submit_close(self, symbol: str, quantity: float) -> CryptoOrderSnapshot: ...

    def submit_protection(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        client_order_id: str,
    ) -> CryptoOrderSnapshot: ...


@dataclass(frozen=True)
class CryptoExitResult:
    ok: bool
    symbol: str
    requested_quantity: float
    filled_quantity: float
    remaining_quantity: float
    realized_pnl: float
    close_order_id: str | None
    canceled_protective_order_ids: tuple[str, ...]
    replacement_protective_order_id: str | None
    residual_protected: bool
    duplicate_blocked: bool
    message: str


class AlpacaCryptoExitCoordinator:
    """Fail-closed lifecycle for closing Alpaca PAPER crypto positions."""

    def __init__(
        self,
        broker: CryptoExitPaperBroker,
        idempotency: IdempotencyStore,
        *,
        ledger_path: str = "var/autotrader/portfolio.db",
        poll_attempts: int = 8,
        poll_delay_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if poll_attempts <= 0 or poll_delay_seconds < 0:
            raise ValueError("poll attempts must be positive and delay cannot be negative")
        self.broker = broker
        self.idempotency = idempotency
        self.ledger_path = ledger_path
        self.poll_attempts = poll_attempts
        self.poll_delay_seconds = poll_delay_seconds
        self.sleeper = sleeper

    def close(
        self,
        symbol: str,
        *,
        stop_price: float,
        quantity: float | None = None,
        strategy_id: str = "autonomous-take-profit",
        now: datetime | None = None,
    ) -> CryptoExitResult:
        if stop_price <= 0:
            raise ValueError("a positive protective stop is required")
        canonical = canonical_crypto_symbol(symbol)
        initial = self.broker.position(canonical)
        if initial is None or initial.quantity <= 1e-12:
            return CryptoExitResult(
                True, canonical, 0.0, 0.0, 0.0, 0.0, None, (), None, True, False, "Position already flat"
            )
        requested = initial.quantity if quantity is None else quantity
        if requested <= 0:
            raise ValueError("close quantity must be positive")
        if requested > initial.quantity + 1e-12:
            raise ValueError("close quantity cannot exceed the current position")

        current_time = now or datetime.now(UTC)
        managed = managed_protective_orders(self.broker, canonical)
        key = self.idempotency.make_key(
            broker="alpaca-crypto-paper",
            symbol=canonical,
            side="sell",
            intent="exit",
            quantity=requested,
            strategy_id=f"{strategy_id}:position={initial.quantity:.12g}",
        )
        if not self.idempotency.reserve(
            key,
            broker="alpaca-crypto-paper",
            symbol=canonical,
            side="sell",
            intent="exit",
            ttl_seconds=900,
            now=current_time,
        ):
            return CryptoExitResult(
                False,
                canonical,
                requested,
                0.0,
                initial.quantity,
                0.0,
                None,
                (),
                None,
                _protection_covers(managed, initial.quantity),
                True,
                "Duplicate crypto exit blocked by persistent idempotency guard",
            )

        canceled: list[str] = []
        for order in managed:
            try:
                self.broker.cancel_order(order.order_id)
                settled = self._wait_terminal(order.order_id)
            except Exception as exc:
                current = self.broker.position(canonical) or initial
                replacement = self._restore_protection(
                    canonical,
                    current.quantity,
                    stop_price,
                    current_time,
                )
                self._mark_failure(key, protected=replacement is not None, now=current_time)
                return CryptoExitResult(
                    False,
                    canonical,
                    requested,
                    0.0,
                    current.quantity,
                    0.0,
                    None,
                    tuple(canceled),
                    replacement.order_id if replacement else None,
                    replacement is not None,
                    False,
                    f"Protective stop cancellation failed: {exc}",
                )
            if settled.status not in TERMINAL_ORDER_STATUSES:
                current = self.broker.position(canonical) or initial
                replacement = self._restore_protection(
                    canonical,
                    current.quantity,
                    stop_price,
                    current_time,
                )
                self._mark_failure(key, protected=replacement is not None, now=current_time)
                return CryptoExitResult(
                    False,
                    canonical,
                    requested,
                    0.0,
                    current.quantity,
                    0.0,
                    None,
                    tuple(canceled),
                    replacement.order_id if replacement else None,
                    replacement is not None,
                    False,
                    "Protective stop cancellation was not confirmed",
                )
            canceled.append(order.order_id)

        before_close = self.broker.position(canonical)
        if before_close is None or before_close.quantity <= 1e-12:
            self.idempotency.mark_submitted(key, None)
            self.idempotency.mark_terminal(
                key,
                "completed",
                ttl_seconds=COMPLETED_EXIT_TTL_SECONDS,
                now=current_time,
            )
            return CryptoExitResult(
                True,
                canonical,
                requested,
                initial.quantity,
                0.0,
                0.0,
                None,
                tuple(canceled),
                None,
                True,
                False,
                "Protective order filled while cancellation settled; position is flat",
            )
        close_quantity = min(requested, before_close.quantity)
        if before_close.available_quantity + 1e-12 < close_quantity:
            replacement = self._restore_protection(canonical, before_close.quantity, stop_price, current_time)
            self._mark_failure(key, protected=replacement is not None, now=current_time)
            return CryptoExitResult(
                False,
                canonical,
                requested,
                0.0,
                before_close.quantity,
                0.0,
                None,
                tuple(canceled),
                replacement.order_id if replacement else None,
                replacement is not None,
                False,
                "Close blocked because broker quantity remained unavailable after confirmed cancellation",
            )

        try:
            submitted = self.broker.submit_close(canonical, close_quantity)
            self.idempotency.mark_submitted(key, submitted.order_id)
        except Exception as exc:
            replacement = self._restore_protection(canonical, before_close.quantity, stop_price, current_time)
            self._mark_failure(key, protected=replacement is not None, now=current_time)
            return CryptoExitResult(
                False,
                canonical,
                requested,
                0.0,
                before_close.quantity,
                0.0,
                None,
                tuple(canceled),
                replacement.order_id if replacement else None,
                replacement is not None,
                False,
                f"Crypto close submission failed; residual protection restoration attempted: {exc}",
            )

        settled_close = self._settle_close(submitted)
        after_close = self.broker.position(canonical)
        remaining = 0.0 if after_close is None else max(after_close.quantity, 0.0)
        filled = min(max(initial.quantity - remaining, 0.0), close_quantity)

        if settled_close.status not in TERMINAL_ORDER_STATUSES:
            try:
                self.broker.cancel_order(settled_close.order_id)
                settled_close = self._wait_terminal(settled_close.order_id)
            except Exception:
                pass
            after_close = self.broker.position(canonical)
            remaining = 0.0 if after_close is None else max(after_close.quantity, 0.0)
            filled = min(max(initial.quantity - remaining, 0.0), close_quantity)

        replacement = None
        if remaining > 1e-12:
            replacement = self._restore_protection(canonical, remaining, stop_price, current_time)
        residual_protected = remaining <= 1e-12 or replacement is not None
        fill_price = settled_close.filled_average_price
        if filled > 1e-12 and fill_price is not None and fill_price > 0:
            realized = (fill_price - initial.average_price) * filled
            self._record_outcome(
                canonical,
                quantity=filled,
                price=fill_price,
                realized_pnl=realized,
                order_id=settled_close.order_id,
                remaining_quantity=remaining,
                occurred_at=current_time,
            )
        else:
            realized = 0.0

        fully_requested = filled + 1e-12 >= close_quantity
        ok = fully_requested and residual_protected
        if ok:
            self.idempotency.mark_terminal(
                key,
                "completed",
                ttl_seconds=COMPLETED_EXIT_TTL_SECONDS,
                now=current_time,
            )
        else:
            self._mark_failure(key, protected=residual_protected, now=current_time)
        message = (
            "Crypto PAPER exit completed and residual protection verified"
            if ok
            else "Crypto PAPER exit incomplete; new exits remain blocked pending reconciliation"
        )
        return CryptoExitResult(
            ok,
            canonical,
            requested,
            filled,
            remaining,
            realized,
            settled_close.order_id,
            tuple(canceled),
            replacement.order_id if replacement else None,
            residual_protected,
            False,
            message,
        )

    def _mark_failure(self, key: str, *, protected: bool, now: datetime) -> None:
        self.idempotency.mark_terminal(
            key,
            "failed_protected" if protected else "failed_unprotected",
            ttl_seconds=(
                PROTECTED_FAILURE_RETRY_SECONDS if protected else UNPROTECTED_FAILURE_TTL_SECONDS
            ),
            now=now,
        )

    def _wait_terminal(self, order_id: str) -> CryptoOrderSnapshot:
        snapshot = self.broker.order(order_id)
        for _ in range(self.poll_attempts - 1):
            if snapshot.status in TERMINAL_ORDER_STATUSES:
                break
            self.sleeper(self.poll_delay_seconds)
            snapshot = self.broker.order(order_id)
        return snapshot

    def _settle_close(self, submitted: CryptoOrderSnapshot) -> CryptoOrderSnapshot:
        if submitted.status in TERMINAL_ORDER_STATUSES:
            return submitted
        return self._wait_terminal(submitted.order_id)

    def _restore_protection(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        now: datetime,
    ) -> CryptoOrderSnapshot | None:
        if quantity <= 1e-12:
            return None
        try:
            existing = managed_protective_orders(self.broker, symbol)
            if _protection_covers(existing, quantity):
                return existing[0]
        except Exception:
            pass
        client_id = f"auto-restore-{now.strftime('%Y%m%dT%H%M%S')}-{symbol.replace('/', '')}-stop"[:48]
        for attempt in range(3):
            try:
                submitted = self.broker.submit_protection(symbol, quantity, stop_price, client_id)
                confirmed = self.broker.order(submitted.order_id)
                if confirmed.status in OPEN_ORDER_STATUSES:
                    return confirmed
            except Exception:
                pass
            if attempt < 2:
                self.sleeper(self.poll_delay_seconds)
        return None

    def _record_outcome(
        self,
        symbol: str,
        *,
        quantity: float,
        price: float,
        realized_pnl: float,
        order_id: str,
        remaining_quantity: float,
        occurred_at: datetime,
    ) -> None:
        ledger = PortfolioLedger(self.ledger_path)
        fill_key = f"alpaca-crypto-exit:{order_id}"
        inserted = ledger.record_fill(
            fill_key=fill_key,
            broker="alpaca-crypto-paper",
            order_id=order_id,
            symbol=symbol,
            side="sell",
            quantity=quantity,
            price=price,
            realized_pnl=realized_pnl,
            occurred_at=occurred_at,
            metadata={
                "pillar": "alpaca_crypto",
                "model_version": "five_pillar_baseline_v1",
                "strategy_version": "autonomous-take-profit-v1",
                "fees": 0.0,
                "net_pnl": realized_pnl,
                "outcome": "closed" if remaining_quantity <= 1e-12 else "partial_close",
            },
        )
        if not inserted:
            return
        loaded = ledger.load_portfolio()
        if loaded is None:
            return
        portfolio, peak = loaded
        position = portfolio.positions.get(symbol)
        portfolio.cash += realized_pnl
        portfolio.equity += realized_pnl
        portfolio.daily_pnl += realized_pnl
        portfolio.weekly_pnl += realized_pnl
        if position is not None:
            position.realized_pnl += realized_pnl
            if remaining_quantity <= 1e-12:
                del portfolio.positions[symbol]
            else:
                position.quantity = remaining_quantity
        ledger.save_portfolio(portfolio, peak_equity=max(peak, portfolio.equity))


def _is_managed_protection(order: CryptoOrderSnapshot, symbol: str) -> bool:
    client_id = order.client_order_id or ""
    return (
        canonical_crypto_symbol(order.symbol) == canonical_crypto_symbol(symbol)
        and order.side.lower() == "sell"
        and order.order_type.lower() in {"stop", "stop_limit", "trailing_stop"}
        and order.status.lower() in OPEN_ORDER_STATUSES
        and client_id.startswith(MANAGED_PROTECTION_PREFIXES)
        and client_id.endswith("-stop")
    )


def canonical_crypto_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("_", "/")
    if "/" in normalized:
        return normalized
    if normalized == "BTCUSD":
        return "BTC/USD"
    if normalized == "ETHUSD":
        return "ETH/USD"
    return normalized


def managed_protective_orders(
    broker: CryptoExitPaperBroker,
    symbol: str,
) -> tuple[CryptoOrderSnapshot, ...]:
    """Rediscover only coordinator-owned protection from broker state."""
    canonical = canonical_crypto_symbol(symbol)
    return tuple(
        order for order in broker.open_orders(canonical) if _is_managed_protection(order, canonical)
    )


def _protection_covers(orders: tuple[CryptoOrderSnapshot, ...], quantity: float) -> bool:
    reserved = sum(max(order.quantity - order.filled_quantity, 0.0) for order in orders)
    return reserved + 1e-12 >= quantity
