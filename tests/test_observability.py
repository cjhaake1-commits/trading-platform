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
