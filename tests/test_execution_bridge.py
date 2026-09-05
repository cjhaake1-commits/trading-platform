from autotrader.execution_bridge import execute_qualified_queue_record
from autotrader.forward_lifecycle import ForwardLifecycle


class Adapter:
    def __init__(self): self.calls = 0
    def submit(self, intent): self.calls += 1; return {"provider_order_id": "PAPER-1", "ack": True}


def test_bridge_fails_closed_before_adapter(tmp_path):
    adapter = Adapter()
    result = execute_qualified_queue_record({"execution_mode": "PAPER", "qualified_signal": True}, adapter=adapter, lifecycle=ForwardLifecycle(tmp_path / "l.db"), now="2026-09-05T01:00:00+00:00")
    assert result["submitted"] is False
    assert adapter.calls == 0


def test_bridge_requires_owned_position_and_records_intent(tmp_path):
    adapter = Adapter(); ledger = ForwardLifecycle(tmp_path / "l.db")
    record = {"execution_mode":"PAPER", "qualified_signal":True, "risk_approved":True, "capital_approved":True, "provider_supported":True, "session_allowed":True, "ownership_allowed":True, "ownership":"PLATFORM_OWNED", "trade_id":"T1", "pillar":"stocks", "engine":"stocks", "instrument":"SPY"}
    result = execute_qualified_queue_record(record, adapter=adapter, lifecycle=ledger, now="2026-09-05T01:00:00+00:00")
    assert result["submitted"] is True and adapter.calls == 1
    assert ledger.counts()["ORDER_INTENT"] == 1
