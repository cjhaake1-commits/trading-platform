"""Reverse evidenced paper principal inflation without erasing losses/history.

The caller must stop ledger writers first. This is not a broker funding/reset
operation and cannot place or cancel any order. An append-only adjustment and
verified SQLite backup preserve the exact before/after state.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

POLICY = "income_6000_v1"
OLD = {"alpaca_equities": 25000.0, "alpaca_crypto": 20000.0,
       "oanda_fx": 15000.0, "alpaca_metals": 10000.0, "ibkr_global": 15000.0}
ADJUSTMENT = -80000.0


def planned_state(state: dict) -> dict:
    fields = ("equity", "cash", "peak_equity", "daily_pnl", "weekly_pnl")
    if any(not isinstance(state.get(k), (float, int)) or not math.isfinite(state[k]) for k in fields):
        raise ValueError("Missing or non-finite logical capital state")
    if abs(state["peak_equity"] - 85000.0) > 0.02:
        raise ValueError("Unrecognized original principal/peak; manual reconciliation required")
    if state["equity"] < 80000 or state["cash"] < 80000:
        raise ValueError("Insufficient uncommitted logical capital to reverse the known inflation")
    after = dict(state)
    for key in ("equity", "cash", "peak_equity"):
        after[key] += ADJUSTMENT
    return after


def migrate(database: Path, backup_dir: Path, *, now=None) -> dict:
    now = now or datetime.now(UTC)
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError("Existing paper ledger is required")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capital_policy_transitions'").fetchone()
        if exists:
            prior = db.execute("SELECT * FROM capital_policy_transitions WHERE policy_id=?", (POLICY,)).fetchone()
            if prior:
                return {"status": "ALREADY_APPLIED", "policy": POLICY, "applied_at": prior["applied_at"]}
        state = db.execute("SELECT * FROM portfolio_state WHERE id=1").fetchone()
        if state is None:
            raise ValueError("Logical portfolio row is missing")
        before = dict(state)
        after = planned_state(before)
        for pillar, amount in OLD.items():
            row = db.execute("SELECT starting_economic_equity,source FROM pillar_day_start_equity WHERE pillar=? AND source='authorized_paper_capital_migration' ORDER BY equity_date DESC LIMIT 1", (pillar,)).fetchone()
            if row is None or float(row["starting_economic_equity"]) != amount:
                raise ValueError("Original allocation migration evidence is incomplete")
        backup = backup_dir / f"portfolio-before-{now.strftime('%Y%m%dT%H%M%S%fZ')}.sqlite"
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(backup)) as copy:
            db.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        db.execute("BEGIN IMMEDIATE")
        try:
            if dict(db.execute("SELECT * FROM portfolio_state WHERE id=1").fetchone()) != before:
                raise ValueError("Ledger changed during backup; no adjustment applied")
            db.execute("CREATE TABLE IF NOT EXISTS capital_policy_transitions (policy_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL, prior_non_kalshi_authorized REAL NOT NULL, non_kalshi_authorized REAL NOT NULL, shared_kalshi_authorized REAL NOT NULL, principal_adjustment REAL NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, backup_path TEXT NOT NULL)")
            db.execute("UPDATE portfolio_state SET equity=?,cash=?,peak_equity=?,updated_at=? WHERE id=1", (after["equity"], after["cash"], after["peak_equity"], now.isoformat()))
            after["updated_at"] = now.isoformat()
            db.execute("INSERT INTO capital_policy_transitions VALUES(?,?,?,?,?,?,?,?,?)", (POLICY, now.isoformat(), 85000.0, 5000.0, 1000.0, ADJUSTMENT, json.dumps(before), json.dumps(after), str(backup)))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"status": "APPLIED", "policy": POLICY, "principal_adjustment": ADJUSTMENT,
            "prior_recorded_pnl_preserved": True, "positions_and_trade_history_untouched": True,
            "backup": str(backup), "after_logical_state": after,
            "scope": "Logical ledger principal adjustment; not a broker balance or new test return"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    if not args.writers_stopped:
        raise SystemExit("Ledger writers must be stopped before an explicit migration")
    print(json.dumps(migrate(args.database, args.backup_dir), indent=2))


if __name__ == "__main__":
    main()
