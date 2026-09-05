import json
from autotrader.runtime_allocator import refresh_allocator


def test_allocator_consumes_queue_and_never_executes(tmp_path):
    queue = tmp_path / "queue.jsonl"
    row = {"decision":"QUEUE_ELIGIBLE", "opportunity": {"pillar":"stocks","engine":"stocks","instrument":"SPY","side":"LONG","expected_return_after_costs":.1,"expected_loss":.01,"confidence":.9,"sample_quality":.8,"liquidity":.9,"correlation":.1,"holding_time_minutes":10,"capital_required":100,"margin_required":0,"drawdown_contribution":.01,"strategy_version":"v1","execution_mode":"PAPER","eligible":True,"rejection_reason":None}}
    queue.write_text(json.dumps(row) + "\n")
    report = refresh_allocator(queue_path=queue, output=tmp_path / "a.json", allocations={"stocks":1000})
    assert report["ranked"] and report["executed"] is False
