from autotrader.audit import SQLiteAuditStore
from autotrader.models import AuditEvent


def test_audit_store_round_trip(tmp_path):
    store = SQLiteAuditStore(tmp_path / "audit.db")
    event_id = store.append(AuditEvent("candidate", "NVDA ranked", {"score": 72.5}))
    assert event_id > 0

    events = store.recent(limit=10)
    assert len(events) == 1
    assert events[0].event_type == "candidate"
    assert events[0].data["score"] == 72.5
