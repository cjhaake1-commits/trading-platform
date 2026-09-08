import sqlite3
from pathlib import Path

import pytest

from scripts.restore_income_capital import OLD, migrate, planned_state


def fixture_db(root):
    path = root / "portfolio.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE portfolio_state(id INTEGER PRIMARY KEY,equity REAL,cash REAL,daily_pnl REAL,weekly_pnl REAL,peak_equity REAL,updated_at TEXT)")
        db.execute("INSERT INTO portfolio_state VALUES(1,83750,83750,-1250,-1250,85000,'before')")
        db.execute("CREATE TABLE pillar_day_start_equity(pillar TEXT,equity_date TEXT,starting_economic_equity REAL,source TEXT)")
        for pillar, amount in OLD.items():
            db.execute("INSERT INTO pillar_day_start_equity VALUES(?,'2026-09-07',?,'authorized_paper_capital_migration')", (pillar, amount))
        db.execute("CREATE TABLE positions(symbol TEXT,quantity REAL)")
        db.execute("INSERT INTO positions VALUES('LEGACY',999)")
        db.execute("CREATE TABLE fills(id TEXT)")
        db.execute("INSERT INTO fills VALUES('history')")
    return path


def test_principal_reversal_preserves_all_recorded_losses_positions_and_history(tmp_path):
    path = fixture_db(tmp_path)
    result = migrate(path, tmp_path / 'backups')
    assert result['after_logical_state']['equity'] == 3750
    assert result['after_logical_state']['daily_pnl'] == -1250
    assert Path(result['backup']).exists()
    assert Path(result['backup']).stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM positions').fetchall() == [('LEGACY', 999)]
        assert db.execute('SELECT * FROM fills').fetchall() == [('history',)]
        assert db.execute('SELECT SUM(starting_economic_equity) FROM pillar_day_start_equity').fetchone()[0] == 85000
    assert migrate(path, tmp_path / 'backups')['status'] == 'ALREADY_APPLIED'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT equity FROM portfolio_state').fetchone()[0] == 3750


def test_unrecognized_or_committed_state_refuses_change(tmp_path):
    path = fixture_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE portfolio_state SET cash=100')
    with pytest.raises(ValueError):
        migrate(path, tmp_path / 'backups')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT equity FROM portfolio_state').fetchone()[0] == 83750


def test_missing_migration_evidence_fails_closed(tmp_path):
    path = fixture_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM pillar_day_start_equity WHERE pillar='oanda_fx'")
    with pytest.raises(ValueError):
        migrate(path, tmp_path / 'backups')


def test_unknown_values_are_not_zeroed():
    with pytest.raises(ValueError):
        planned_state(dict(equity=float('nan'), cash=83750, peak_equity=85000, daily_pnl=-1250, weekly_pnl=-1250))
