from __future__ import annotations

import hashlib
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
                CREATE TABLE IF NOT EXISTS pillar_day_start_equity (
                    pillar TEXT NOT NULL,
                    equity_date TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    day_start_timestamp TEXT NOT NULL,
                    starting_economic_equity REAL NOT NULL,
                    source TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    PRIMARY KEY (pillar, equity_date)
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
                CREATE TABLE IF NOT EXISTS entry_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    canonical_symbol TEXT NOT NULL,
                    broker_symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    regime TEXT,
                    approved_entry REAL NOT NULL,
                    requested_quantity REAL NOT NULL,
                    approved_notional REAL NOT NULL,
                    approved_stop REAL NOT NULL,
                    approved_target REAL,
                    approved_dollar_risk REAL NOT NULL,
                    allocation_at_approval REAL NOT NULL,
                    portfolio_risk_at_approval REAL NOT NULL,
                    risk_engine_decision TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    client_order_id_namespace TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    broker_order_id TEXT,
                    submitted_quantity REAL,
                    filled_quantity REAL,
                    broker_confirmed_position_quantity REAL,
                    average_fill_price REAL,
                    reconciliation_status TEXT,
                    reconciliation_difference REAL,
                    protection_order_id TEXT,
                    protection_quantity REAL,
                    protection_stop REAL,
                    protection_state TEXT,
                    close_order_ids_json TEXT,
                    realized_pnl REAL,
                    fees_costs REAL,
                    closed_at TEXT,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manifest_archive (
                    manifest_id TEXT PRIMARY KEY,
                    archived_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    source_lifecycle_state TEXT NOT NULL
                );
                """
            )

    def save_pillar_day_start_equity(
        self,
        *,
        pillar: str,
        equity_date: str,
        timezone: str,
        day_start_timestamp: str,
        starting_economic_equity: float,
        source: str,
    ) -> None:
        """Persist the immutable daily economic-equity denominator per pillar."""
        if not pillar or not equity_date or starting_economic_equity <= 0:
            raise ValueError("pillar, equity_date, and positive starting equity are required")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pillar_day_start_equity
                   (pillar, equity_date, timezone, day_start_timestamp,
                    starting_economic_equity, source, persisted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(pillar, equity_date) DO NOTHING""",
                (pillar, equity_date, timezone, day_start_timestamp,
                 float(starting_economic_equity), source, datetime.now(UTC).isoformat()),
            )

    def load_pillar_day_start_equity(self, *, pillar: str, equity_date: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pillar_day_start_equity WHERE pillar=? AND equity_date=?",
                (pillar, equity_date),
            ).fetchone()
        return dict(row) if row else None

    def archive_manifest(self, manifest_id: str, *, category: str, reason: str, evidence: list[str]) -> None:
        """Append an auditable archive disposition; never delete the source manifest."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT lifecycle_state FROM entry_manifests WHERE manifest_id = ?", (manifest_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown manifest: {manifest_id}")
            connection.execute(
                "INSERT OR REPLACE INTO manifest_archive VALUES (?, ?, ?, ?, ?, ?)",
                (manifest_id, datetime.now(UTC).isoformat(), category, reason, json.dumps(evidence), row[0]),
            )

    def mark_manifest_terminal(self, manifest_id: str, *, lifecycle_state: str, metadata: dict[str, object]) -> None:
        """Record a terminal broker outcome without deleting the audit manifest."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE entry_manifests SET lifecycle_state=?, metadata_json=?, updated_at=? WHERE manifest_id=?",
                (lifecycle_state, json.dumps(metadata, default=str), datetime.now(UTC).isoformat(), manifest_id),
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

    @staticmethod
    def manifest_fingerprint(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def save_entry_manifest(
        self,
        *,
        manifest_id: str,
        created_at: datetime | str,
        broker: str,
        environment: str,
        pillar: str,
        canonical_symbol: str,
        broker_symbol: str,
        side: str,
        model_version: str,
        strategy_version: str,
        confidence: float,
        regime: str | None,
        approved_entry: float,
        requested_quantity: float,
        approved_notional: float,
        approved_stop: float,
        approved_target: float | None,
        approved_dollar_risk: float,
        allocation_at_approval: float,
        portfolio_risk_at_approval: float,
        risk_engine_decision: str,
        lifecycle_state: str,
        client_order_id_namespace: str,
        fingerprint: str,
        broker_order_id: str | None = None,
        submitted_quantity: float | None = None,
        filled_quantity: float | None = None,
        broker_confirmed_position_quantity: float | None = None,
        average_fill_price: float | None = None,
        reconciliation_status: str | None = None,
        reconciliation_difference: float | None = None,
        protection_order_id: str | None = None,
        protection_quantity: float | None = None,
        protection_stop: float | None = None,
        protection_state: str | None = None,
        close_order_ids: list[str] | None = None,
        realized_pnl: float | None = None,
        fees_costs: float | None = None,
        closed_at: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        created_at_dt = _utc_datetime(created_at)
        closed_at_dt = None if closed_at is None else _utc_datetime(closed_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO entry_manifests (
                    manifest_id, created_at, broker, environment, pillar,
                    canonical_symbol, broker_symbol, side, model_version,
                    strategy_version, confidence, regime, approved_entry,
                    requested_quantity, approved_notional, approved_stop,
                    approved_target, approved_dollar_risk, allocation_at_approval,
                    portfolio_risk_at_approval, risk_engine_decision,
                    lifecycle_state, client_order_id_namespace, fingerprint,
                    broker_order_id, submitted_quantity, filled_quantity,
                    broker_confirmed_position_quantity, average_fill_price,
                    reconciliation_status, reconciliation_difference,
                    protection_order_id, protection_quantity, protection_stop,
                    protection_state, close_order_ids_json, realized_pnl,
                    fees_costs, closed_at, updated_at, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(manifest_id) DO UPDATE SET
                    broker=excluded.broker,
                    environment=excluded.environment,
                    pillar=excluded.pillar,
                    canonical_symbol=excluded.canonical_symbol,
                    broker_symbol=excluded.broker_symbol,
                    side=excluded.side,
                    model_version=excluded.model_version,
                    strategy_version=excluded.strategy_version,
                    confidence=excluded.confidence,
                    regime=excluded.regime,
                    approved_entry=excluded.approved_entry,
                    requested_quantity=excluded.requested_quantity,
                    approved_notional=excluded.approved_notional,
                    approved_stop=excluded.approved_stop,
                    approved_target=excluded.approved_target,
                    approved_dollar_risk=excluded.approved_dollar_risk,
                    allocation_at_approval=excluded.allocation_at_approval,
                    portfolio_risk_at_approval=excluded.portfolio_risk_at_approval,
                    risk_engine_decision=excluded.risk_engine_decision,
                    lifecycle_state=excluded.lifecycle_state,
                    client_order_id_namespace=excluded.client_order_id_namespace,
                    fingerprint=excluded.fingerprint,
                    broker_order_id=excluded.broker_order_id,
                    submitted_quantity=excluded.submitted_quantity,
                    filled_quantity=excluded.filled_quantity,
                    broker_confirmed_position_quantity=excluded.broker_confirmed_position_quantity,
                    average_fill_price=excluded.average_fill_price,
                    reconciliation_status=excluded.reconciliation_status,
                    reconciliation_difference=excluded.reconciliation_difference,
                    protection_order_id=excluded.protection_order_id,
                    protection_quantity=excluded.protection_quantity,
                    protection_stop=excluded.protection_stop,
                    protection_state=excluded.protection_state,
                    close_order_ids_json=excluded.close_order_ids_json,
                    realized_pnl=excluded.realized_pnl,
                    fees_costs=excluded.fees_costs,
                    closed_at=excluded.closed_at,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    manifest_id,
                    created_at_dt.isoformat(),
                    broker,
                    environment,
                    pillar,
                    canonical_symbol,
                    broker_symbol,
                    side,
                    model_version,
                    strategy_version,
                    confidence,
                    regime,
                    approved_entry,
                    requested_quantity,
                    approved_notional,
                    approved_stop,
                    approved_target,
                    approved_dollar_risk,
                    allocation_at_approval,
                    portfolio_risk_at_approval,
                    risk_engine_decision,
                    lifecycle_state,
                    client_order_id_namespace,
                    fingerprint,
                    broker_order_id,
                    submitted_quantity,
                    filled_quantity,
                    broker_confirmed_position_quantity,
                    average_fill_price,
                    reconciliation_status,
                    reconciliation_difference,
                    protection_order_id,
                    protection_quantity,
                    protection_stop,
                    protection_state,
                    json.dumps(close_order_ids or [], sort_keys=True),
                    realized_pnl,
                    fees_costs,
                    None if closed_at_dt is None else closed_at_dt.isoformat(),
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

    def load_entry_manifest(self, manifest_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM entry_manifests WHERE manifest_id = ?",
                (manifest_id,),
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
        close_ids = result.get("close_order_ids_json")
        if isinstance(close_ids, str):
            try:
                result["close_order_ids"] = json.loads(close_ids)
            except Exception:
                result["close_order_ids"] = []
        return result

    def latest_entry_manifest_for_symbol(
        self,
        canonical_symbol: str,
        *,
        broker: str | None = None,
    ) -> dict[str, object] | None:
        query = "SELECT * FROM entry_manifests WHERE canonical_symbol = ?"
        params: list[object] = [canonical_symbol]
        if broker is not None:
            query += " AND broker = ?"
            params.append(broker)
        query += " ORDER BY created_at DESC, manifest_id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        result = dict(row)
        metadata = result.get("metadata_json")
        if isinstance(metadata, str):
            try:
                result["metadata"] = json.loads(metadata)
            except Exception:
                result["metadata"] = {}
        close_ids = result.get("close_order_ids_json")
        if isinstance(close_ids, str):
            try:
                result["close_order_ids"] = json.loads(close_ids)
            except Exception:
                result["close_order_ids"] = []
        return result

    @staticmethod
    def unresolved_entry_states() -> tuple[str, ...]:
        return (
            "approved_manifest",
            "order_submitted",
            "order_pending",
            "filled_position_pending",
            "reconciliation_pending",
            "protection_pending",
            "protection_submitted",
            "active",
            "reconciliation_deferred",
            "unprotected_position",
            "manual_review_required",
        )

    def latest_unresolved_entry_manifest_for_symbol(
        self,
        canonical_symbol: str,
        *,
        broker: str | None = None,
    ) -> dict[str, object] | None:
        query = "SELECT * FROM entry_manifests WHERE canonical_symbol = ? AND lifecycle_state IN ({})".format(
            ",".join("?" for _ in self.unresolved_entry_states())
        )
        params: list[object] = [canonical_symbol, *self.unresolved_entry_states()]
        if broker is not None:
            query += " AND broker = ?"
            params.append(broker)
        query += " ORDER BY created_at DESC, manifest_id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        result = dict(row)
        metadata = result.get("metadata_json")
        if isinstance(metadata, str):
            try:
                result["metadata"] = json.loads(metadata)
            except Exception:
                result["metadata"] = {}
        close_ids = result.get("close_order_ids_json")
        if isinstance(close_ids, str):
            try:
                result["close_order_ids"] = json.loads(close_ids)
            except Exception:
                result["close_order_ids"] = []
        return result

    def unresolved_entry_manifests(
        self,
        *,
        broker: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM entry_manifests WHERE lifecycle_state IN ({})".format(
            ",".join("?" for _ in self.unresolved_entry_states())
        )
        params: list[object] = [*self.unresolved_entry_states()]
        if broker is not None:
            query += " AND broker = ?"
            params.append(broker)
        query += " ORDER BY created_at ASC, manifest_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        output: list[dict[str, object]] = []
        for row in rows:
            result = dict(row)
            metadata = result.get("metadata_json")
            if isinstance(metadata, str):
                try:
                    result["metadata"] = json.loads(metadata)
                except Exception:
                    result["metadata"] = {}
            close_ids = result.get("close_order_ids_json")
            if isinstance(close_ids, str):
                try:
                    result["close_order_ids"] = json.loads(close_ids)
                except Exception:
                    result["close_order_ids"] = []
            output.append(result)
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


def _utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
