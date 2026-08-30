from scripts.create_overnight_final_report import build_report


def test_final_report_refuses_verification_without_unresolved_failure_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/reports").mkdir(parents=True)
    (tmp_path / "var/reports/overnight-forward-campaign.json").write_text(
        '{"safety":{"live_trading_enabled":false,"real_money_orders":0},"runtime_evidence":{"unresolved_runtime_failures":1},"engines":{},"providers":{}}'
    )
    (tmp_path / "var/reports/overnight-progress.json").write_text('{"runtime":{"healthy":true},"git_sha":"abc"}')
    report = build_report()
    assert report.startswith("HIGH_ACTIVITY_PAPER_LAB_V1 — NOT YET VERIFIED")
