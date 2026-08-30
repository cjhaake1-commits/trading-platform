from __future__ import annotations

import importlib
from pathlib import Path


def test_streamlit_entrypoint_imports_with_src_layout():
    module = importlib.import_module("streamlit_app")
    assert module.__name__ == "streamlit_app"


def test_streamlit_dashboard_copy_includes_six_pillars_and_benchmarks():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "SIX-PILLAR AUTONOMOUS TRADING COMMAND CENTER" in source
    assert "CHRIS HAAKE CAPITAL SYSTEMS" in source
    assert "US Stocks / ETFs" in source
    assert "Forex" in source
    assert "Crypto" in source
    assert "Metals / Commodities" in source
    assert "International" in source
    assert "20%–40% Daily Return" in source
    assert "$20–$305 Daily Realized Cash" in source


def test_requirements_dashboard_installs_local_package_editably():
    requirements = Path("requirements-dashboard.txt").read_text(encoding="utf-8")
    assert "-e ." in requirements


def test_kalshi_card_uses_stateful_health_and_learning_funnel():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "def _kalshi_status" in source
    assert "CONNECTED / PERPS ACCOUNT BLOCKED" in source
    assert "Learning Funnel".lower() in source.lower()
    assert "Cross-Market Samples" in source
    assert "Legacy Exposure" not in source
    assert "Research Health" in source
    assert "Learning Health" in source
    assert "Evidence Maturity" in source
    assert "kalshi_pillar_observations" in source


def test_crypto_and_international_use_execution_truth_states():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "READY — EVALUATING OPPORTUNITIES" in source
    assert "READY — NO QUALIFIED EDGE" in source
    assert "READY — WAITING FOR ELIGIBLE MARKET SESSION" in source
    assert "WHY NO NEW TRADE?" in source


def test_crypto_broker_symbol_normalization_preserves_position_ownership():
    module = importlib.import_module("streamlit_app")
    assert module._canonical_symbol("CRVUSD") == "CRV/USD"
    assert module._canonical_symbol("CRV/USD") == "CRV/USD"
    rows = module._build_live_positions(
        [{"broker": "Alpaca Paper", "symbol": "CRV/USD", "classification": "VALID_STRATEGY_POSITION"}],
        [{"broker": "Alpaca Paper", "symbol": "CRV/USD", "pillar": "Crypto", "market_value": 985.27}],
    )
    assert len(rows) == 1
    assert rows[0]["pillar"] == "Crypto"
    assert rows[0]["market_value"] == 985.27


def test_saxo_position_fields_normalize_provider_position():
    module = importlib.import_module("streamlit_app")
    item = module._saxo_position_fields({
        "PositionBase": {"Amount": 2, "OpenPrice": 125.0, "SourceOrderId": "saxo-1", "AssetType": "Stock"},
        "PositionView": {"Exposure": 260.0, "ProfitLossOnTrade": 10.0},
        "DisplayAndFormat": {"Symbol": "7203:xnas"},
    })
    assert item["order_id"] == "saxo-1"
    assert item["quantity"] == 2
    assert item["cost_basis"] == 250.0
    assert item["market_value"] == 260.0


def test_dashboard_does_not_hardcode_international_or_crypto_to_zero():
    dashboard = Path("streamlit_app.py").read_text(encoding="utf-8")
    runtime = Path("src/autotrader/runtime_app.py").read_text(encoding="utf-8")
    assert 'pillar_status["International"]["positions"] = 0' not in dashboard
    assert 'if pillar == "International":\n                deployed = 0.0' not in runtime
    assert 'unrealized_values["International"] = 0.0' not in runtime
    assert "CRV/USD PAPER position active" not in dashboard


def test_crypto_working_orders_override_flat_snapshot_state():
    module = importlib.import_module("streamlit_app")
    state, connection, reason = module._derive_pillar_state(
        "Crypto",
        {"last_finished_at": "fresh"},
        {"connected": True, "positions": 0, "working_orders": 2, "state": "FLAT"},
        [{"job": "autonomous-paper-trading", "crypto_scanned": 30, "crypto_qualified": 0}],
    )
    assert state == "ACTIVE — ORDER WORKING"
    assert connection == "CONNECTED"
    assert "pending" in reason.lower()


def test_kalshi_parent_state_is_derived_from_child_engines():
    module = importlib.import_module("streamlit_app")
    state, reason = module._kalshi_parent_state({
        "connection": "CONNECTED",
        "predictions_auth": "CONNECTED",
        "perps_rest": "CONNECTED",
        "predictions_funnel": {"scanned": 100},
        "perps_funnel": {"scanned": 34},
        "predictions_rejection": "INSUFFICIENT_SPREAD_OR_LIQUIDITY",
        "perps_rejection": "PROVIDER_SUBMISSION_REJECTED",
        "perps_positions": 0,
        "perps_open_orders": 0,
        "predictions_positions": 0,
        "predictions_open_orders": 0,
    })
    assert state == "READY — EVALUATING OPPORTUNITIES"
    assert "Predictions" in reason and "Perps" in reason


def test_kalshi_provider_read_failure_is_not_rendered_as_flat_healthy():
    module = importlib.import_module("streamlit_app")
    state, reason = module._kalshi_parent_state({
        "connection": "CONNECTED",
        "predictions_auth": "CONNECTED",
        "perps_rest": "CONNECTED",
        "predictions_provider_state": "CONNECTED",
        "perps_provider_state": "DEGRADED",
        "perps_provider_error": "HTTPError: HTTP 500",
        "predictions_funnel": {"scanned": 100},
        "perps_funnel": {"scanned": 34},
    })
    assert state == "DEGRADED — CHILD ENGINE"
    assert "HTTP 500" in reason


def test_return_and_cash_harvest_objectives_are_separate():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "TOTAL DAILY RETURN" in source
    assert "REALIZED CASH GENERATED" in source
    assert "harvest_floor_progress" in source
    assert "daily_performance.json" in source


def test_streamlit_dashboard_reads_normalized_ledger_authority():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "def load_authoritative_accounting" in source
    assert "PortfolioLedger" in source
    assert '"authoritative_accounting"' in source


def test_streamlit_dashboard_defaults_auto_refresh_off():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert 'st.session_state.get("dashboard_auto_refresh", False)' in source


def test_provider_health_uses_lab_utc_cutoff_not_sqlite_wall_clock():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "timedelta(hours=24)" in source
    assert "datetime('now', '-24 hours')" not in source


def test_dashboard_exposes_kalshi_candidate_telemetry():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "Kalshi candidate telemetry" in source
    assert "candidate-telemetry-{family}.jsonl" in source
    assert '"Calibrated edge"' in source
