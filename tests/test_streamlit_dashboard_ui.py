from __future__ import annotations

import importlib
from pathlib import Path


def test_streamlit_entrypoint_imports_with_src_layout():
    module = importlib.import_module("streamlit_app")
    assert module.__name__ == "streamlit_app"


def test_streamlit_dashboard_copy_includes_five_pillars_and_benchmarks():
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "FIVE-PILLAR AUTONOMOUS TRADING COMMAND CENTER" in source
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
