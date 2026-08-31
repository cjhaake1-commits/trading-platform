import json

import pytest

from autotrader.simulated_execution_test_mode import run_readiness_canary


def test_canary_is_paper_only_and_excluded(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    record = run_readiness_canary(pillar="Crypto", provider="Alpaca", symbol="BTC/USD", environment="PAPER", path=tmp_path / "c.json")
    assert record.classification == "READINESS_CANARY" and record.cancelled and record.residual_position is False
    assert json.loads((tmp_path / "c.json").read_text())[0]["filled"] is True


def test_canary_rejects_production_environment(tmp_path):
    with pytest.raises(RuntimeError):
        run_readiness_canary(pillar="Crypto", provider="Alpaca", symbol="BTC/USD", environment="PRODUCTION", path=tmp_path / "c.json")
