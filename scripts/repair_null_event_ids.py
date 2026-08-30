#!/usr/bin/env python3
"""Backfill deterministic event identities for pre-V1 ledger rows only."""
from __future__ import annotations

import sqlite3


def repair(db_path: str = "var/autotrader/paper_experiment.db") -> int:
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT rowid FROM activity_observations WHERE event_id IS NULL ORDER BY rowid").fetchall()
        for (rowid,) in rows:
            db.execute("UPDATE activity_observations SET event_id=? WHERE rowid=? AND event_id IS NULL", (f"LEGACY-EVENT-{rowid}", rowid))
        db.commit()
    return len(rows)


if __name__ == "__main__":
    print(f"repaired={repair()}")
