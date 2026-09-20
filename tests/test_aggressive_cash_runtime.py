import json

from scripts.run_aggressive_cash_runtime import run


def test_runtime_reports_no_trade_without_eligible_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/autotrader").mkdir(parents=True)
    (tmp_path / "var/autotrader/verification-epoch.json").write_text(json.dumps({"verification_epoch_id": "VE-x", "started_at": "2026-09-15T20:49:44+00:00"}))
    (tmp_path / "opportunities.json").write_text(json.dumps({"opportunities": [{"status": "BLOCKED_CAPITAL"}]}))
    result = run(opportunity_path=tmp_path / "opportunities.json", output=tmp_path / "runtime.json")
    assert result["runtime_state"] == "RUNTIME_READY_NO_EXECUTION"
    assert result["orders_submitted"] == 0
    assert result["paper_only"] is True
