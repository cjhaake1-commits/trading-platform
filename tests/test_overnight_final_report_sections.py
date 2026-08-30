from scripts.create_overnight_final_report import build_report


def test_final_report_contains_requested_handoff_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/reports").mkdir(parents=True)
    for name, value in {
        "overnight-forward-campaign.json": '{"safety":{"live_trading_enabled":false,"real_money_orders":0},"runtime_evidence":{"unresolved_runtime_failures":0},"engines":{},"providers":{}}',
        "overnight-progress.json": '{"runtime":{"healthy":true},"git_sha":"abc"}',
        "daily-learning-2026-08-30.json": '{"actual_results":"UNKNOWN","shadow_scorecard":"UNKNOWN","activity":{}}',
        "research-queue.json": '{"items":[]}',
    }.items():
        (tmp_path / "var/reports" / name).write_text(value)
    report = build_report()
    for number in range(1, 26):
        assert f"## {number}." in report
    assert "70-item acceptance checklist" in report
    assert "does not hardcode a stale test count" in report
