from pathlib import Path

import performance_board as board


def _snapshot(**crypto):
    return {"pillar_performance": {"Crypto": crypto}}


def test_performance_board_has_read_only_automatic_refresh():
    source = Path("performance_board.py").read_text(encoding="utf-8")
    assert 'meta http-equiv="refresh" content="20"' in source
    assert "submit_order" not in source


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
        {},
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


def test_normalized_accounting_snapshot_is_board_authority():
    rows = board.build_pillars({
        "pillar_performance": {"Crypto": {"realized_pnl": 999.0}},
        "pillar_accounting_snapshot": [{
            "pillar": "Crypto", "provider_observed": True, "freshness": "FRESH",
            "accounting_status": "ACCOUNTING_VERIFIED", "economic_equity": 795.59,
            "available_cash": 795.59, "deployed_cash": 0.0, "pending": 0.0,
            "realized_today": -204.41, "unrealized": 0.0, "total_pnl": -204.41,
            "daily_return": -0.20441, "positions": 0, "working_orders": 0,
        }]
    }, {}, {}, [], {"connected": False})
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["equity"] == 795.59
    assert crypto["available"] == 795.59
    assert crypto["realized"] == -204.41


def test_missing_provider_snapshot_cannot_verify():
    rows = board.build_pillars({"pillar_accounting_snapshot": [{
        "pillar": "Crypto", "provider_observed": False, "freshness": "MISSING",
        "accounting_status": "ACCOUNTING_UNVERIFIED", "economic_equity": None,
        "available_cash": None, "deployed_cash": None, "pending": None,
        "realized_today": None, "unrealized": None, "total_pnl": None,
    }]}, {}, {}, [], {"connected": False})
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["accounting_status"] == "ACCOUNTING_UNVERIFIED"
    assert crypto["provider_available"] is False


def test_fresh_crypto_provider_state_overrides_stale_ledger_snapshot():
    rows = board.build_pillars(
        {"pillar_accounting_snapshot": [{"pillar": "Crypto", "provider_observed": True,
          "freshness": "FRESH", "accounting_status": "ACCOUNTING_VERIFIED",
          "economic_equity": 1.0, "deployed_cash": 0.0, "available_cash": 1.0,
          "realized_today": 0.0, "unrealized": 0.0}]},
        {}, {"Crypto": {"connected": True, "positions": 1, "working_orders": 2,
          "account_equity": 102630.8, "strategy_cost_basis": 100.0,
          "unrealized_pnl": 4.0}},
        {},
        [{"pillar": "Crypto", "quantity": 2, "average_price": 50, "market_value": 110}],
        {"connected": False},
    )
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["equity"] == 102630.8
    assert crypto["positions"] == 1
    assert crypto["working_orders"] == 2


def test_provider_truth_section_keeps_kalshi_mutation_separate():
    source = Path("performance_board.py").read_text(encoding="utf-8")
    assert "International & Kalshi Provider Truth" in source
    assert "PROVIDER MUTATION BLOCKED — USER_NOT_FOUND" in source


def test_crypto_provider_failure_does_not_use_stale_accounting_values():
    rows = board.build_pillars(
        {"pillar_accounting_snapshot": [{"pillar": "Crypto", "economic_equity": 999.0, "available_cash": 999.0}]},
        {}, {"Crypto": {"connected": False, "error": "timeout"}}, {}, [], {"connected": False},
    )
    crypto = next(row for row in rows if row["name"] == "Crypto")
    assert crypto["equity"] is None
    assert crypto["available"] is None
    assert crypto["state"] == "UNAVAILABLE"


def test_authoritative_snapshot_preserves_unknowns_and_totals(tmp_path):
    rows = [{"name": "Crypto", "equity": 100.0, "deployed": 25.0, "pending": 0.0,
             "available": 75.0, "positions": 1, "working_orders": 0, "realized": 2.0,
             "unrealized": 3.0, "freshness": "FRESH", "state": "ACTIVE"},
            {"name": "International", "equity": None, "deployed": None, "pending": None,
             "available": None, "positions": None, "working_orders": None, "realized": None,
             "unrealized": None, "freshness": "ERROR", "state": "UNAVAILABLE"}]
    payload = board.write_authoritative_portfolio_snapshot(rows, output=tmp_path / "snapshot.json", observed_at="2026-08-31T00:00:00+00:00")
    assert payload["source"] == "direct provider/runtime reads"
    assert payload["totals"]["equity"] is None
    assert payload["pillars"][0]["provider"] == "Alpaca"


def test_saxo_reconciliation_does_not_adopt_legacy_position(tmp_path):
    rows = [{"PositionId": "p1", "NetPositionId": "uic__Share",
             "PositionBase": {"Uic": 123, "AssetType": "Stock", "Amount": 2,
                               "OpenPrice": 10, "SourceOrderId": "legacy-1",
                               "ExecutionTimeOpen": "2026-08-31T00:00:00Z"},
             "PositionView": {"CurrentPrice": 11, "Exposure": 22,
                              "MarketValue": 22, "ProfitLossOnTrade": 2}}]
    payload = board.write_international_position_reconciliation(rows, {"current-1"}, output=tmp_path / "intl.json")
    assert payload["position_count"] == 1
    assert payload["platform_owned_positions"] == 0
    assert payload["external_legacy_unknown_positions"] == 1


def test_shared_alpaca_equity_is_counted_once(tmp_path):
    rows = [{"name": name, "equity": 100.0, "deployed": 10.0, "pending": 0.0,
             "available": 90.0, "positions": 1, "working_orders": 0, "realized": 0.0,
             "unrealized": 0.0, "freshness": "FRESH", "state": "ACTIVE"}
            for name in ("stocks", "Crypto", "Metals / Commodities")]
    payload = board.write_authoritative_portfolio_snapshot(rows, output=tmp_path / "snapshot.json")
    assert payload["totals"]["equity"] == 100.0
    assert payload["totals"]["deployed"] == 30.0
