from scripts.create_research_queue import build_queue


def test_research_queue_is_ranked_and_paper_only(tmp_path):
    source = tmp_path / "daily.json"
    source.write_text(
        '{"activity":{"Crypto":{"top_bottlenecks":{"NO_EDGE":12}}},'
        '"shadow_by_strategy":{"crypto.momentum.v1":{"pillar":"Crypto",'
        '"completed":31,"evidence_classification":"EARLY_SIGNAL"}}}'
    )
    report = build_queue(str(source))
    assert report["safety"] == {"mode": "paper", "live_trading_enabled": False, "real_money_orders": 0}
    assert report["items"][0]["priority"] == "HIGH"
    assert all("recommended_measurement" in item for item in report["items"])
    assert "threshold" in report["policy"]


def test_research_queue_preserves_insufficient_evidence(tmp_path):
    source = tmp_path / "missing.json"
    report = build_queue(str(source))
    assert report["items"][0]["classification"] == "INSUFFICIENT_EVIDENCE"
