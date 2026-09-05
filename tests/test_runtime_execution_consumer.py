from autotrader.runtime_execution_consumer import RuntimeExecutionConsumer


def test_consumer_persists_provider_block_and_is_idempotent(tmp_path):
    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    record = {"intent_id": "I1", "execution_mode": "PAPER", "qualified_signal": True}
    first = consumer.consume(record)
    second = consumer.consume(record)
    assert first["reason"] == "PROVIDER_UNSUPPORTED"
    assert second["reason"] == "PROVIDER_UNSUPPORTED"


def test_consumer_dispatches_only_when_all_bridge_gates_pass(tmp_path):
    class Adapter:
        def submit(self, record): return {"provider_order_id": "P1", "ack": True}
    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    record = {"intent_id":"I2", "trade_id":"I2", "execution_mode":"PAPER", "qualified_signal":True, "risk_approved":True, "capital_approved":True, "provider_supported":True, "session_allowed":True, "ownership_allowed":True, "ownership":"PLATFORM_OWNED", "pillar":"stocks", "engine":"stocks", "instrument":"SPY"}
    assert consumer.consume(record, adapter=Adapter(), now="2026-09-05T01:00:00+00:00")["state"] == "SUBMITTED"


def test_consumer_rejects_margin_shortfall_before_provider_call(tmp_path):
    class Adapter:
        def submit(self, record):
            raise AssertionError("provider must not be called")
    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    record = {"intent_id": "M1", "trade_id": "M1", "execution_mode": "PAPER",
              "qualified_signal": True, "risk_approved": True, "capital_approved": True,
              "provider_supported": True, "session_allowed": True, "ownership_allowed": True,
              "ownership": "PLATFORM_OWNED", "margin_required": 200, "margin_available": 100}
    assert consumer.consume(record, adapter=Adapter())["reason"] == "MARGIN_LIMIT"
