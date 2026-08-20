from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import AssetClass, PortfolioState, Position


class PortfolioLedger:
    """SQLite-backed logical master portfolio state.

    Broker cash remains physically separate, but risk and drawdown decisions can
    consume one reconciled logical portfolio. State writes are transactional and
    restart-safe. Raw market data does not belong in this database.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    daily_pnl REAL NOT NULL,
                    weekly_pnl REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    asset_class TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    average_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    initial_stop_price REAL,
                    highest_price REAL,
                    opened_at TEXT,
                    broker TEXT,
                    broker_position_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fills (
                    fill_key TEXT PRIMARY KEY,
                    broker TEXT NOT NULL,
                    order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    occurred_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS broker_state (
                    broker TEXT PRIMARY KEY,
                    cash REAL,
                    equity REAL,
                    buying_power REAL,
                    margin_available REAL,
                    last_transaction_id TEXT,
                    reconciled_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crypto_entry_state (
                    symbol TEXT PRIMARY KEY,
                    broker TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    requested_quantity REAL,
                    submitted_quantity REAL,
                    broker_filled_quantity REAL,
                    broker_position_quantity REAL,
                    reconciliation_difference REAL,
                    reconciliation_tolerance REAL,
                    reconciliation_status TEXT NOT NULL,
                    protection_state TEXT NOT NULL,
                    protection_quantity REAL,
                    stop_price REAL,
                    fill_price REAL,
                    client_order_id TEXT,
                    protective_order_id TEXT,
                    entry_order_id TEXT,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                """
            )

    def save_portfolio(self, portfolio: PortfolioState, *, peak_equity: float) -> None:
        if peak_equity <= 0:
            raise ValueError("peak_equity must be positive")
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO portfolio_state
                    (id, equity, cash, daily_pnl, weekly_pnl, peak_equity, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    equity=excluded.equity,
                    cash=excluded.cash,
                    daily_pnl=excluded.daily_pnl,
                    weekly_pnl=excluded.weekly_pnl,
                    peak_equity=MAX(portfolio_state.peak_equity, excluded.peak_equity),
                    updated_at=excluded.updated_at
                """,
                (
                    portfolio.equity,
                    portfolio.cash,
                    portfolio.daily_pnl,
                    portfolio.weekly_pnl,
                    peak_equity,
                    now,
                ),
            )
            connection.execute("DELETE FROM positions")
            for position in portfolio.positions.values():
                connection.execute(
                    """
                    INSERT INTO positions (
                        symbol, asset_class, quantity, average_price, stop_price,
                        realized_pnl, initial_stop_price, highest_price, opened_at,
                        broker, broker_position_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        position.symbol,
                        position.asset_class.value,
                        position.quantity,
                        position.average_price,
                        position.stop_price,
                        position.realized_pnl,
                        position.initial_stop_price,
                        position.highest_price,
                        None if position.opened_at is None else position.opened_at.isoformat(),
                        now,
                    ),
                )

    def load_portfolio(self) -> tuple[PortfolioState, float] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM portfolio_state WHERE id = 1").fetchone()
            if row is None:
                return None
            position_rows = connection.execute("SELECT * FROM positions").fetchall()

        positions: dict[str, Position] = {}
        for item in position_rows:
            opened_at = None
            if item["opened_at"]:
                opened_at = datetime.fromisoformat(item["opened_at"])
            positions[item["symbol"]] = Position(
                symbol=item["symbol"],
                asset_class=AssetClass(item["asset_class"]),
                quantity=float(item["quantity"]),
                average_price=float(item["average_price"]),
                stop_price=float(item["stop_price"]),
                realized_pnl=float(item["realized_pnl"]),
                initial_stop_price=item["initial_stop_price"],
                highest_price=item["highest_price"],
                opened_at=opened_at,
            )
        return (
            PortfolioState(
                equity=float(row["equity"]),
                cash=float(row["cash"]),
                daily_pnl=float(row["daily_pnl"]),
                weekly_pnl=float(row["weekly_pnl"]),
                positions=positions,
            ),
            float(row["peak_equity"]),
        )

    def record_fill(
        self,
        *,
        fill_key: str,
        broker: str,
        order_id: str | None,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        realized_pnl: float = 0.0,
        occurred_at: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        if not fill_key.strip():
            raise ValueError("fill_key is required")
        when = occurred_at or datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO fills
                    (fill_key, broker, order_id, symbol, side, quantity, price,
                     realized_pnl, occurred_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_key,
                    broker,
                    order_id,
                    symbol,
                    side,
                    quantity,
                    price,
                    realized_pnl,
                    when.isoformat(),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            return cursor.rowcount == 1

    def save_broker_state(
        self,
        broker: str,
        *,
        cash: float | None = None,
        equity: float | None = None,
        buying_power: float | None = None,
        margin_available: float | None = None,
        last_transaction_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO broker_state (
                    broker, cash, equity, buying_power, margin_available,
                    last_transaction_id, reconciled_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker) DO UPDATE SET
                    cash=excluded.cash,
                    equity=excluded.equity,
                    buying_power=excluded.buying_power,
                    margin_available=excluded.margin_available,
                    last_transaction_id=excluded.last_transaction_id,
                    reconciled_at=excluded.reconciled_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    broker,
                    cash,
                    equity,
                    buying_power,
                    margin_available,
                    last_transaction_id,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )

    def save_crypto_entry_state(
        self,
        symbol: str,
        *,
        broker: str,
        lifecycle_state: str,
        requested_quantity: float | None,
        submitted_quantity: float | None,
        broker_filled_quantity: float | None,
        broker_position_quantity: float | None,
        reconciliation_difference: float | None,
        reconciliation_tolerance: float | None,
        reconciliation_status: str,
        protection_state: str,
        protection_quantity: float | None,
        stop_price: float | None,
        fill_price: float | None = None,
        client_order_id: str | None = None,
        protective_order_id: str | None = None,
        entry_order_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO crypto_entry_state (
                    symbol, broker, lifecycle_state, requested_quantity, submitted_quantity,
                    broker_filled_quantity, broker_position_quantity, reconciliation_difference,
                    reconciliation_tolerance, reconciliation_status, protection_state,
                    protection_quantity, stop_price, fill_price, client_order_id,
                    protective_order_id, entry_order_id, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    broker=excluded.broker,
                    lifecycle_state=excluded.lifecycle_state,
                    requested_quantity=excluded.requested_quantity,
                    submitted_quantity=excluded.submitted_quantity,
                    broker_filled_quantity=excluded.broker_filled_quantity,
                    broker_position_quantity=excluded.broker_position_quantity,
                    reconciliation_difference=excluded.reconciliation_difference,
                    reconciliation_tolerance=excluded.reconciliation_tolerance,
                    reconciliation_status=excluded.reconciliation_status,
                    protection_state=excluded.protection_state,
                    protection_quantity=excluded.protection_quantity,
                    stop_price=excluded.stop_price,
                    fill_price=excluded.fill_price,
                    client_order_id=excluded.client_order_id,
                    protective_order_id=excluded.protective_order_id,
                    entry_order_id=excluded.entry_order_id,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    symbol,
                    broker,
                    lifecycle_state,
                    requested_quantity,
                    submitted_quantity,
                    broker_filled_quantity,
                    broker_position_quantity,
                    reconciliation_difference,
                    reconciliation_tolerance,
                    reconciliation_status,
                    protection_state,
                    protection_quantity,
                    stop_price,
                    fill_price,
                    client_order_id,
                    protective_order_id,
                    entry_order_id,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )

    def load_crypto_entry_state(self, symbol: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM crypto_entry_state WHERE symbol = ?", (symbol,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        metadata = result.get("metadata_json")
        if isinstance(metadata, str):
            try:
                result["metadata"] = json.loads(metadata)
            except Exception:
                result["metadata"] = {}
        return result

    def crypto_entry_states(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM crypto_entry_state ORDER BY symbol").fetchall()
        output = []
        for row in rows:
            record = dict(row)
            metadata = record.get("metadata_json")
            if isinstance(metadata, str):
                try:
                    record["metadata"] = json.loads(metadata)
                except Exception:
                    record["metadata"] = {}
            output.append(record)
        return output

    def snapshot(self) -> dict[str, object]:
        loaded = self.load_portfolio()
        with self._connect() as connection:
            brokers = [dict(row) for row in connection.execute("SELECT * FROM broker_state")]
            fills = connection.execute("SELECT COUNT(*) AS count FROM fills").fetchone()["count"]
        if loaded is None:
            return {"portfolio": None, "peak_equity": None, "brokers": brokers, "fill_count": fills}
        portfolio, peak = loaded
        return {
            "portfolio": {
                "equity": portfolio.equity,
                "cash": portfolio.cash,
                "daily_pnl": portfolio.daily_pnl,
                "weekly_pnl": portfolio.weekly_pnl,
                "positions": {symbol: asdict(position) for symbol, position in portfolio.positions.items()},
            },
            "peak_equity": peak,
            "brokers": brokers,
            "fill_count": fills,
        }
