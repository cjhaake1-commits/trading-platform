from autotrader.learning_ingestion import LearningIngestor


def test_learning_ingestion_accepts_only_owned_resolved_outcome(tmp_path):
    ingestor = LearningIngestor(tmp_path / "l.db")
    base = {"ownership":"PLATFORM_OWNED", "decision_at":"2026-09-05T01:00:00Z", "outcome_at":"2026-09-05T01:05:00Z", "realized_pnl":2, "pillar":"stocks", "strategy":"momentum"}
    assert ingestor.ingest(outcome_id="O1", outcome=base)
    assert not ingestor.ingest(outcome_id="O1", outcome=base)
    assert ingestor.count() == 1


def test_learning_ingestion_rejects_protected_and_lookahead(tmp_path):
    ingestor = LearningIngestor(tmp_path / "l.db")
    assert not ingestor.ingest(outcome_id="O2", outcome={"ownership":"LEGACY", "decision_at":"2026-09-05T01:00:00Z", "outcome_at":"2026-09-05T01:05:00Z"})
    assert not ingestor.ingest(outcome_id="O3", outcome={"ownership":"PLATFORM_OWNED", "decision_at":"2026-09-05T02:00:00Z", "outcome_at":"2026-09-05T01:05:00Z"})


def test_learning_health_publishes_only_clean_forward_outcomes(tmp_path):
    ingestor = LearningIngestor(tmp_path / "l.db")
    base = {"ownership":"PLATFORM_OWNED", "strategy":"good", "decision_at":"2026-09-05T01:00:00Z",
            "outcome_at":"2026-09-05T01:05:00Z", "realized_pnl":2}
    assert ingestor.ingest(outcome_id="O1", outcome=base)
    assert not ingestor.ingest(outcome_id="O2", outcome={**base, "ownership":"LEGACY"})
    payload = ingestor.publish_strategy_health(tmp_path / "health.json", minimum_sample=2)
    assert payload["strategies"][0]["state"] == "INSUFFICIENT_SAMPLE"
    assert payload["strategies"][0]["source"] == "CLEAN_FORWARD_PAPER_OUTCOMES"
