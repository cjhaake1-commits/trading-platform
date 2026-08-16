from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import AuditEvent


class SQLiteAuditStore:
    """Small persistent append-only audit store for scanner and execution events."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type)"
            )

    def append(self, event: AuditEvent) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_events (event_type, message, data_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.message,
                    json.dumps(event.data, sort_keys=True, default=str),
                    event.created_at.isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = 100, event_type: str | None = None) -> list[AuditEvent]:
        query = "SELECT event_type, message, data_json, created_at FROM audit_events"
        params: list[object] = []
        if event_type is not None:
            query += " WHERE event_type = ?"
            params.append(event_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(limit, 0))

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            AuditEvent(
                event_type=row[0],
                message=row[1],
                data=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]
