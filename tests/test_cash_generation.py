import json

from autotrader.cash_generation import classify_manifest_record, write_cash_generation_reports


def test_pre_epoch_fixture_is_classified_without_being_counted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    epoch = {"verification_epoch_id": "VE-x", "started_at": "2026-09-15T20:49:44+00:00"}
    assert classify_manifest_record({"verification_epoch_id": "VE-x", "timestamp": "2026-09-05T01:00:00+00:00", "order_intent_id": "I2", "symbol": "SPY"}, **epoch) == "PRE_EPOCH_TEST"
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"verification_epoch_id": "VE-bb9bd184ffb0ad64", "timestamp": "2026-09-05T01:00:00+00:00", "order_intent_id": "I2", "symbol": "SPY", "ownership_classification": "PLATFORM_OWNED_CURRENT_EXPERIMENT"}) + "\n")
    daily, weekly = write_cash_generation_reports(manifest_path=manifest, report_dir=tmp_path / "reports")
    report = json.loads(daily.read_text())
    assert report["closed_trades"] == 0
    assert report["test_contamination"]["status"] == "ISOLATED"
    assert weekly.exists()


def test_report_does_not_convert_unknown_pnl_to_profit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var/autotrader").mkdir(parents=True)
    (tmp_path / "var/autotrader/verification-epoch.json").write_text(json.dumps({"verification_epoch_id": "VE-bb9bd184ffb0ad64", "started_at": "2026-09-15T20:49:44+00:00"}))
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"verification_epoch_id": "VE-bb9bd184ffb0ad64", "timestamp": "2026-09-16T12:00:00+00:00", "ownership_classification": "PLATFORM_OWNED_CURRENT_EXPERIMENT", "event_type": "POSITION_CLOSED", "realized_pnl": "UNKNOWN"}) + "\n")
    daily, _ = write_cash_generation_reports(manifest_path=manifest, report_dir=tmp_path / "reports")
    assert json.loads(daily.read_text())["realized_cash_pnl"] == "UNKNOWN"
