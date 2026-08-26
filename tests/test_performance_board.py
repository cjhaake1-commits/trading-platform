from pathlib import Path

import performance_board as board


def _snapshot(**crypto):
    return {"pillar_performance": {"Crypto": crypto}}


def test_performance_board_has_no_automatic_refresh():
    source = Path("performance_board.py").read_text(encoding="utf-8")
    assert "meta http-equiv" not in source
    assert "st_autorefresh" not in source
    assert "auto-refresh 20s" not in source


def test_closed_crypto_activity_is_not_exposure():
    rows = board.build_pillars(
        _snapshot(realized_today=12.5, completed_trades_today=1),
        {"Crypto": {"connected": True, "positions": 0}}, {}, [], {"connected": False},
    )
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["deployed"] == 0
    assert crypto["completed_today"] == 1
    assert crypto["realized"] == 12.5


def test_open_crypto_position_is_deployed():
    rows = board.build_pillars(
        _snapshot(),
        {"Crypto": {"connected": True, "positions": 1}}, {},
        [{"pillar": "Crypto", "quantity": 2, "average_price": 50, "market_value": 110}],
        {"connected": False},
    )
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["deployed"] == 100


def test_provider_failure_is_unavailable():
    rows = board.build_pillars({}, {"Crypto": {"connected": False}}, {}, [], {"connected": False})
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["provider_available"] is False
    assert crypto["state"] == "UNAVAILABLE"

