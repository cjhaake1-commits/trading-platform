import json
from datetime import UTC, datetime

from autotrader.runtime_queue import persist_runtime_queue_decision


def test_runtime_queue_records_missing_economics_as_rejection(tmp_path):
    path = tmp_path / "queue.jsonl"
    record = persist_runtime_queue_decision(
        job_name="oanda-fx-paper-trading", pillar="oanda_fx", provider="OANDA",
        now=datetime(2026, 9, 5, tzinfo=UTC), data={"candidate": "EUR_USD", "qualified": True}, path=path,
    )
    assert record["decision"] == "QUEUE_REJECTED"
    assert record["rejection_reason"] == "INSUFFICIENT_CANONICAL_ECONOMICS"
    assert record["execution_side_effects"] == "NONE"
    assert json.loads(path.read_text())["decision"] == "QUEUE_REJECTED"


def test_runtime_queue_accepts_complete_engine_evidence(tmp_path):
    record = persist_runtime_queue_decision(
        job_name="alpaca-metals-paper-trading", pillar="alpaca_metals", provider="Alpaca",
        now=datetime(2026, 9, 5, tzinfo=UTC),
        data={"symbol": "GLD", "qualified": True, "risk_approved": True,
              "expected_return_after_costs": .03, "expected_loss": .01,
              "confidence": .9, "sample_quality": .8, "liquidity": .9,
              "correlation": .1, "capital_required": 100, "drawdown_contribution": .01},
        path=tmp_path / "queue.jsonl",
    )
    assert record["decision"] == "QUEUE_ELIGIBLE"
    assert record["execution_side_effects"] == "NONE"


def test_runtime_queue_preserves_explicit_closed_session_reason(tmp_path):
    record = persist_runtime_queue_decision(
        job_name="saxo-international-paper-trading", pillar="International", provider="Saxo",
        now=datetime(2026, 9, 5, tzinfo=UTC),
        data={"candidate": "MU:xmil", "execution_state": "READY / EVALUATING",
              "execution_open": 0},
        path=tmp_path / "queue.jsonl",
    )
    assert record["rejection_reason"] == "SESSION_CLOSED"
