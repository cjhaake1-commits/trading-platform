from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    reason: str
    feed_ok: bool
    broker_ok: bool
    ledger_ok: bool
    risk_ok: bool
    duplicate_ok: bool


class IdempotencyStore:
    """Persistent duplicate-order guard shared across restarts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_intents (
                    idempotency_key TEXT PRIMARY KEY,
                    broker TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    broker_order_id TEXT,
                    status TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(
        *,
        broker: str,
        symbol: str,
        side: str,
        intent: str,
        quantity: float | None = None,
        notional: float | None = None,
        strategy_id: str = "",
        decision_bucket: str = "",
    ) -> str:
        material = "|".join(
            [
                broker.strip().lower(),
                symbol.strip().upper(),
                side.strip().lower(),
                intent.strip().lower(),
                "" if quantity is None else f"q={quantity:.12g}",
                "" if notional is None else f"n={notional:.12g}",
                strategy_id.strip(),
                decision_bucket.strip(),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def reserve(
        self,
        key: str,
        *,
        broker: str,
        symbol: str,
        side: str,
        intent: str,
        ttl_seconds: int = 60,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        expires = current + timedelta(seconds=ttl_seconds)
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM order_intents WHERE expires_at < ?", (current.isoformat(),))
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO order_intents (
                    idempotency_key, broker, symbol, side, intent,
                    created_at, expires_at, broker_order_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'reserved')
                """,
                (
                    key,
                    broker,
                    symbol,
                    side,
                    intent,
                    current.isoformat(),
                    expires.isoformat(),
                ),
            )
            return cursor.rowcount == 1

    def mark_submitted(self, key: str, broker_order_id: str | None) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE order_intents SET broker_order_id = ?, status = 'submitted' WHERE idempotency_key = ?",
                (broker_order_id, key),
            )

    def release(self, key: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM order_intents WHERE idempotency_key = ?", (key,))


class ExecutionReadinessGate:
    """Fail-closed summary gate before broker submission."""

    @staticmethod
    def evaluate(
        *,
        feed_ok: bool,
        broker_ok: bool,
        ledger_ok: bool,
        risk_ok: bool,
        duplicate_ok: bool,
    ) -> ExecutionReadiness:
        checks = {
            "feed": feed_ok,
            "broker": broker_ok,
            "ledger": ledger_ok,
            "risk": risk_ok,
            "duplicate": duplicate_ok,
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            return ExecutionReadiness(
                False,
                "execution blocked: " + ", ".join(failed),
                feed_ok,
                broker_ok,
                ledger_ok,
                risk_ok,
                duplicate_ok,
            )
        return ExecutionReadiness(
            True,
            "execution readiness checks passed",
            feed_ok,
            broker_ok,
            ledger_ok,
            risk_ok,
            duplicate_ok,
        )
