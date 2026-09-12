import json

from autotrader import observability as obs


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "ROOT", tmp_path)
    monkeypatch.setattr(obs, "BOUNDARY", tmp_path / "boundary.json")
    monkeypatch.setattr(obs, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(obs, "STATUS", tmp_path / "status.json")

def test_detector_rejects_preboundary_and_flags(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    boundary = obs.ensure_boundary(runtime_instance_id="r1")
    obs.record({"event_type":"FILL","event_time_utc":"2000-01-01T00:00:00+00:00",
                "intent_id":"old","is_historical":True}, boundary=boundary)
    assert obs.first_qualifying_trade()["qualified"] is False

def test_detector_qualifies_natural_postboundary_order(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    boundary = obs.ensure_boundary(runtime_instance_id="r2")
    obs.record({"event_type":"PROVIDER_ACK","pillar":"Crypto","instrument":"BTC/USD",
                "provider":"Alpaca","candidate_id":"c1","intent_id":"i1","order_id":"o1",
                "platform_owned":False}, boundary=boundary)
    result = obs.first_qualifying_trade()
    assert result["qualified"] is True and result["intent_id"] == "i1"

def test_public_status_is_sanitized(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    payload = obs.publish_status()
    assert payload["live_trading_enabled"] is False
    assert "SECRET" not in json.dumps(payload).upper()


def test_enabled_fresh_non_kalshi_jobs_are_not_reported_disabled(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    status = {
        "healthy": True,
        "jobs": {
            name: {"disabled": False, "last_finished_at": "2026-09-12T21:00:00+00:00"}
            for name in (
                "autonomous-paper-trading",
                "oanda-fx-paper-trading",
                "alpaca-metals-paper-trading",
                "saxo-international-paper-trading",
            )
        },
    }
    payload = obs.publish_status(status)
    for pillar in ("stocks", "crypto", "forex", "metals", "international"):
        assert payload["six_pillars"][pillar]["enabled"] is True
        assert payload["six_pillars"][pillar]["last_activity_at"]


def test_disabled_or_missing_job_is_distinguished_from_missing_evidence(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    payload = obs.publish_status({"healthy": True, "jobs": {"autonomous-paper-trading": {"disabled": True}}})
    assert payload["six_pillars"]["stocks"]["enabled"] is False
    assert payload["six_pillars"]["forex"]["enabled"] is False
    assert payload["six_pillars"]["forex"]["last_activity_at"] is None
