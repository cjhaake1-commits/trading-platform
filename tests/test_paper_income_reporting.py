from datetime import UTC, datetime, timedelta
from pathlib import Path

from portfolio_reporting import PILLARS, build_report, normalize_accounting, runtime_view

NOW = datetime(2026, 9, 8, 23, tzinfo=UTC)


def rows():
    return [dict(pillar=name, observed_at=NOW.isoformat(), provider_observed=1,
        allocation_cap=1000.0, starting_equity=1000.0, economic_equity=1000.0,
        deployed_cash=100.0, available_cash=900.0, pending=0.0,
        realized_today=0.0, unrealized=0.0, total_pnl=0.0, positions=1,
        working_orders=0, trades_today=0, position_market_value=100.0,
        accounting_status="ACCOUNTING_VERIFIED") for name in PILLARS]


def test_six_pillar_totals_are_not_shared_broker_balances():
    report = normalize_accounting(rows(), now=NOW)
    assert report["authorized_capital"] == 6000
    assert report["equity"] == 6000
    assert report["deployed"] == 600
    assert report["available"] == 5400
    assert report["net_income"] is None
    assert report["trades_today"] is None


def test_missing_pillar_and_null_are_not_zero():
    data = rows()
    data[0]["unrealized"] = None
    assert normalize_accounting(data, now=NOW)["unrealized"] is None
    report = normalize_accounting(data[:-1], now=NOW)
    assert report["status"] == "PARTIAL"
    assert report["equity"] is None
    assert len(report["pillars"]) == 6


def test_stale_bad_baseline_and_unverified_data_block_totals():
    for key, value in (("observed_at", (NOW - timedelta(days=7)).isoformat()),
        ("allocation_cap", 25000), ("accounting_status", "ACCOUNTING_UNVERIFIED"),
        ("provider_observed", False), ("economic_equity", 1001)):
        data = rows()
        data[0][key] = value
        result = normalize_accounting(data, now=NOW)
        assert result["status"] == "PARTIAL"
        assert result["equity"] is None


def test_nan_inf_and_duplicate_pillars_do_not_pollute_totals():
    data = rows()
    data[0]["unrealized"] = float("nan")
    data[1]["total_pnl"] = float("inf")
    result = normalize_accounting(data, now=NOW)
    assert result["unrealized"] is None and result["total_pnl"] is None
    assert normalize_accounting(data + [data[0]], now=NOW)["equity"] is None


def test_oldest_required_timestamp_controls_freshness():
    data = rows()
    data[0]["observed_at"] = (NOW - timedelta(seconds=90)).isoformat()
    result = normalize_accounting(data, now=NOW)
    assert result["observed_at"] == data[0]["observed_at"]


def test_absent_ledger_remains_absent_and_unavailable(tmp_path):
    report = build_report(tmp_path, now=NOW)
    assert report["equity"] is None
    assert not (tmp_path / "var").exists()
    assert report["runtime"]["healthy"] is False


def test_stale_runtime_cannot_claim_active_engines():
    old = (NOW - timedelta(days=1)).isoformat()
    runtime = {"last_heartbeat_at": old, "healthy": True, "live_trading_enabled": False,
        "jobs": {"autonomous-paper-trading": {"last_finished_at": old, "disabled": False}}}
    result = runtime_view(runtime, {}, now=NOW)
    assert not result["healthy"]
    assert not result["pillars"]["Crypto"]["active"]


def test_paper_budget_regression_and_shared_kalshi_losses():
    from autotrader.capital_allocations import SIX_PILLAR_ALLOCATIONS, SIX_PILLAR_BASE_CAPITAL, kalshi_pool_available
    assert SIX_PILLAR_BASE_CAPITAL == 6000
    assert len(SIX_PILLAR_ALLOCATIONS) == 6
    assert set(SIX_PILLAR_ALLOCATIONS.values()) == {1000.0}
    assert kalshi_pool_available(committed=500, pending=300, realized_profit=-100) == 100


def test_optional_audit_database_without_table_is_empty_evidence(tmp_path):
    import sqlite3

    from autotrader.learning import RealizedOutcomeLearner
    path = tmp_path / "audit.db"
    with sqlite3.connect(path):
        pass
    assert RealizedOutcomeLearner(audit_path=str(path)).manifest_evidence() == []


def test_ui_uses_shared_contract_not_nonexistent_legacy_context_keys():
    text = Path("dashboard_simple.py").read_text()
    assert 'st.fragment(run_every="20s")' in text
    assert 'ctx.get("fund"' not in text
    assert "build_report" in text
    assert "UNAVAILABLE" in text


def test_foundation_includes_kalshi_and_does_not_hide_overbudget_positions():
    text = Path("src/autotrader/runtime_app.py").read_text()
    assert "SIX_PILLAR_ALLOCATIONS[key_map[pillar]]" in text
    assert 'reason = "legacy allocation breach segregated from current fund"' not in text


def test_publisher_recovers_diverged_branch_without_force_push():
    text = Path("scripts/publish_runtime_status.py").read_text()
    assert '"merge", "--no-edit", "origin/runtime-status"' in text
    assert "--force" not in text
    assert "build_report" in text
