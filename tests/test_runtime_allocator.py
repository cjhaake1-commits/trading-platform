import json
from autotrader.runtime_allocator import refresh_allocator
from autotrader.runtime_execution_consumer import RuntimeExecutionConsumer
from autotrader.forward_lifecycle import ForwardLifecycle
from autotrader.forward_economic_lifecycle import EconomicLifecycle


def test_allocator_consumes_queue_and_never_executes(tmp_path):
    queue = tmp_path / "queue.jsonl"
    row = {"decision":"QUEUE_ELIGIBLE", "opportunity": {"pillar":"stocks","engine":"stocks","instrument":"SPY","side":"LONG","expected_return_after_costs":.1,"expected_loss":.01,"confidence":.9,"sample_quality":.8,"liquidity":.9,"correlation":.1,"holding_time_minutes":10,"capital_required":100,"margin_required":0,"drawdown_contribution":.01,"strategy_version":"v1","execution_mode":"PAPER","eligible":True,"rejection_reason":None}}
    queue.write_text(json.dumps(row) + "\n")
    report = refresh_allocator(queue_path=queue, output=tmp_path / "a.json", allocations={"stocks":1000})
    assert report["ranked"] and report["executed"] is False


def test_allocator_competes_from_one_released_economic_pool(tmp_path):
    queue = tmp_path / "queue.jsonl"
    rows = []
    for pillar, instrument in (("stocks", "SPY"), ("crypto", "BTC/USD")):
        rows.append({"decision":"QUEUE_ELIGIBLE", "opportunity": {
            "pillar":pillar,"engine":pillar,"instrument":instrument,"side":"LONG",
            "expected_return_after_costs":.1,"expected_loss":.01,"confidence":.9,
            "sample_quality":.8,"liquidity":.9,"correlation":.1,"holding_time_minutes":10,
            "capital_required":100,"margin_required":0,"drawdown_contribution":.01,
            "strategy_version":"v1","execution_mode":"PAPER","eligible":True,"rejection_reason":None}})
    queue.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = refresh_allocator(queue_path=queue, output=tmp_path / "a.json",
                               allocations={"economic_portfolio": 150})
    assert len(report["allocations"]) == 1
    assert report["allocations"][0]["allocation_scope"] == "SINGLE_ECONOMIC_PORTFOLIO"
    assert report["capital_available_after_allocation"] == 50


def test_allocated_capital_reaches_paper_consumer_and_new_owned_position(tmp_path):
    queue = tmp_path / "queue.jsonl"
    row = {"decision":"QUEUE_ELIGIBLE", "opportunity": {
        "pillar":"forex","engine":"fx","instrument":"EUR/USD","side":"LONG",
        "expected_return_after_costs":.2,"expected_loss":.01,"confidence":.9,
        "sample_quality":.9,"liquidity":.9,"correlation":.1,"holding_time_minutes":5,
        "capital_required":100,"margin_required":0,"drawdown_contribution":.01,
        "strategy_version":"v1","execution_mode":"PAPER","eligible":True,"rejection_reason":None}}
    queue.write_text(json.dumps(row) + "\n")
    allocation = refresh_allocator(queue_path=queue, output=tmp_path / "a.json",
                                   allocations={"economic_portfolio": 100})["allocations"][0]
    class Paper:
        def submit(self, intent):
            return {"provider_order_id": "PAPER-REDEPLOY-1", "ack": True, "fill": True}
    consumer = RuntimeExecutionConsumer(tmp_path / "i.db",
        lifecycle=ForwardLifecycle(tmp_path / "l.db"),
        economic=EconomicLifecycle(tmp_path / "e.db"))
    result = consumer.consume({**allocation, "intent_id":"redeploy-1",
        "trade_id":"redeploy-1", "qualified_signal":True, "risk_approved":True,
        "capital_approved":True, "provider_supported":True, "session_allowed":True,
        "ownership_allowed":True, "ownership":"PLATFORM_OWNED"},
        adapter=Paper(), now="2026-09-05T23:30:00+00:00")
    assert result["state"] == "SUBMITTED"
    assert consumer.economic.metrics()["capital_redeployed"] == 100
