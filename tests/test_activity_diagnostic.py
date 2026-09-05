import json
from autotrader.activity_diagnostic import persist_activity


def test_activity_diagnostic_persists_exact_idle_reason(tmp_path):
    row = persist_activity({"economic_capital": 100, "capital_deployed": 25,
                            "capital_available": 75, "last_rejection_reason": "RISK_LIMIT"},
                           path=tmp_path / "activity.jsonl")
    assert row["utilization"] == 0.25
    assert row["why_is_capital_idle"] == "RISK_LIMIT"
    assert json.loads((tmp_path / "activity.jsonl").read_text())["idle_capital_by_reason"] == {"RISK_LIMIT": 1}
