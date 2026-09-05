from autotrader.forward_lifecycle import ForwardLifecycle


def test_lifecycle_is_idempotent_and_protects_unknown(tmp_path):
    ledger = ForwardLifecycle(tmp_path / "lifecycle.db")
    base = dict(trade_id="t1", occurred_at="2026-09-05T01:00:00+00:00", pillar="stocks", engine="stocks", instrument="SPY")
    assert ledger.record(stage="DECISION", payload={}, **base)
    assert ledger.record(stage="DECISION", payload={}, **base)
    assert not ledger.record(stage="OUTCOME", payload={"ownership": "UNKNOWN"}, **base)
    assert ledger.counts()["DECISION"] == 1
    assert ledger.counts()["OUTCOME"] == 0


def test_owned_lifecycle_can_reach_outcome(tmp_path):
    ledger = ForwardLifecycle(tmp_path / "lifecycle.db")
    base = dict(trade_id="t2", occurred_at="2026-09-05T01:00:00+00:00", pillar="stocks", engine="stocks", instrument="SPY")
    for stage in ("DECISION", "ORDER_INTENT", "ORDER", "ACK", "FILL", "OWNERSHIP", "OUTCOME", "LEARNING"):
        assert ledger.record(stage=stage, payload={"ownership": "PLATFORM_OWNED"}, **base)
    assert ledger.counts()["OUTCOME"] == 1
