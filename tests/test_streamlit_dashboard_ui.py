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
