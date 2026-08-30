from autotrader.intelligence_learning import IntelligenceLearningTree
from autotrader.research_universe import ResearchUniverse, Security
from autotrader.sec_scheduler import SecResearchScheduler


def test_sec_bootstrap_is_bounded_and_auth_required_without_user_agent(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "research.db")
    universe = ResearchUniverse((Security("ABC", "1"), Security("DEF", "2")), "UNION_CORE")
    result = SecResearchScheduler(tree, universe=universe, user_agent=None).run_batch()
    assert result["status"] == "AUTH_REQUIRED"
    assert result["issuers_remaining"] == 2


def test_sec_checkpoint_resumes_cursor(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "research.db")
    tree.checkpoint("sec_bootstrap", status="DEGRADED", records=1, error="fixture")
    universe = ResearchUniverse((Security("ABC", "1"), Security("DEF", "2")), "UNION_CORE")
    result = SecResearchScheduler(tree, universe=universe, user_agent=None).run_batch()
    assert result["issuers_completed"] == 1


def test_sec_schema_keeps_filing_identity_and_live_mode_separate(tmp_path):
    tree = IntelligenceLearningTree(tmp_path / "research.db")
    SecResearchScheduler(tree, universe=ResearchUniverse((Security("ABC", "1"),)), user_agent=None).run_batch()
    with tree._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sec_filings)")}
    assert {"accession", "content_hash", "mode"} <= columns
