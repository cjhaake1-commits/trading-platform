"""Durable, idempotent forward capital reservations."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class CapitalReservations:
    def __init__(self, path: str | Path = "var/autotrader/capital-reservations.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, pillar TEXT, local_submission_id TEXT UNIQUE, amount REAL, created_at TEXT, released_at TEXT, state TEXT, released_amount REAL NOT NULL DEFAULT 0)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(reservations)")}
            if "released_amount" not in columns:
                db.execute("ALTER TABLE reservations ADD COLUMN released_amount REAL NOT NULL DEFAULT 0")

    def reserve(self, *, reservation_id: str, pillar: str, local_submission_id: str, amount: float, created_at: str) -> bool:
        if amount <= 0:
            raise ValueError("capital reservation amount must be positive")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT state FROM reservations WHERE reservation_id=? OR local_submission_id=?", (reservation_id, local_submission_id)).fetchone()
            if row:
                return row[0] == "RESERVED"
            db.execute("INSERT INTO reservations (reservation_id,pillar,local_submission_id,amount,created_at,released_at,state,released_amount) VALUES (?,?,?,?,?,?,?,?)", (reservation_id, pillar, local_submission_id, amount, created_at, None, "RESERVED", 0.0))
        return True

    def release(self, *, reservation_id: str, released_at: str,
                completion_event: str, amount: float | None = None,
                reason: str = "CONFIRMED_EXIT_OR_CANCEL") -> bool:
        if completion_event not in {"EXIT_FILLED", "CANCELED"}:
            raise ValueError("capital may be released only after confirmed exit fill or cancellation")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT amount, released_amount, state FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if not row or row[2] == "RELEASED":
                return False
            total, released, _ = row
            release_amount = total - released if amount is None else amount
            if release_amount <= 0 or release_amount > total - released:
                raise ValueError("release amount exceeds remaining reservation")
            new_released = released + release_amount
            state = "RELEASED:" + reason if new_released == total else "PARTIALLY_RELEASED:" + reason
            cur = db.execute("UPDATE reservations SET released_at=?, state=?, released_amount=? WHERE reservation_id=? AND state NOT LIKE 'RELEASED:%'", (released_at, state, new_released, reservation_id))
        return cur.rowcount == 1
