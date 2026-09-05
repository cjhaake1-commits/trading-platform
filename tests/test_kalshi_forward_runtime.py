from autotrader.kalshi_forward_runtime import consume_forward
from autotrader.runtime_execution_consumer import RuntimeExecutionConsumer


def candidate(**overrides):
    value = {
        "ticker": "KXTEST", "qualified": True,
        "expected_return_after_costs": 0.04, "risk_approved": True,
        "capital_approved": True, "provider_supported": True,
        "session_allowed": True, "capital_required": 10,
    }
    value.update(overrides)
    return value


def test_predictions_and_perps_share_fail_closed_consumer(tmp_path):
    class Adapter:
        def submit(self, record):
            return {"provider_order_id": record["intent_id"], "ack": True}

    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    for family in ("predictions", "perps"):
        result = consume_forward(candidate(ticker=f"{family}-ticker"), family=family,
                                 consumer=consumer, adapter=Adapter())
        assert result["state"] == "SUBMITTED"


def test_legacy_kalshi_exposure_cannot_enter_forward_path(tmp_path):
    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    result = consume_forward(candidate(ownership="LEGACY", legacy_provider_exposure=True),
                             family="predictions", consumer=consumer)
    assert result["reason"] == "PROTECTED_OWNERSHIP"


def test_unqualified_kalshi_candidate_is_rejected_without_adapter(tmp_path):
    consumer = RuntimeExecutionConsumer(tmp_path / "intents.db")
    result = consume_forward(candidate(expected_return_after_costs=-0.01),
                             family="perps", consumer=consumer)
    assert result["reason"] == "STRATEGY_NOT_QUALIFIED"
