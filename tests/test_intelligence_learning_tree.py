from __future__ import annotations

import inspect

from autotrader.corporate_features import derive_features
from autotrader.intelligence_fusion import IntelligenceFusionEngine
from autotrader.intelligence_orchestrator import IntelligenceOrchestrator
from autotrader.research_platform import ResearchStore
from autotrader.sec_edgar import normalize_filing


def test_sec_normalization_is_point_in_time_and_versions_amendments():
    first = normalize_filing({"accession": "0001-23-000001", "cik": "1", "form": "10-Q", "filed": "2023-05-01", "period": "2023-03-31", "facts": {"revenue": 10}}, raw=b"a")
    amended = normalize_filing({"accession": "0001-23-000001", "cik": "1", "form": "10-Q/A", "filed": "2023-06-01", "period": "2023-03-31", "amended": True, "facts": {"revenue": 11}}, raw=b"b")
    assert first.record()["as_of_date"] == "2023-05-01"
    assert amended.amended and amended.content_hash != first.content_hash
    assert first.record()["research_id"] != amended.record()["research_id"]


def test_corporate_features_do_not_mix_without_required_duration_values():
    result = derive_features({"revenue": 100, "gross_profit": 40, "net_income": 10}, effective_at="2024-01-01")
    assert result["gross_margin"] == 0.4
    assert "cash_debt" not in result


def test_fusion_explicitly_denies_execution_and_penalizes_concentrated_hype():
    result = IntelligenceFusionEngine().fuse("ABC", crowd={"attention_velocity": 2, "author_concentration": .8}, market={"relative_volume": 2})
    assert result.execution_authorized is False
    assert result.manipulation_risk == .8
    assert "MARKET_NOT_CONFIRMED" not in result.reason_codes


def test_orchestrator_persists_fusion_to_existing_learning_tree(tmp_path):
    store = ResearchStore(tmp_path / "research.db")
    result = IntelligenceOrchestrator(store).run_once()
    rows = store.research("intelligence_fusion")
    assert result["fusion_observations"] == 3
    assert len(rows) == 3
    assert all(row["broker_control"] == 0 for row in rows)


def test_intelligence_modules_have_no_order_interface():
    source = "".join(inspect.getsource(module) for module in (
        __import__("autotrader.intelligence_orchestrator", fromlist=["x"]),
        __import__("autotrader.intelligence_fusion", fromlist=["x"]),
        __import__("autotrader.intelligence_persistence", fromlist=["x"]),
    ))
    assert "submit_order" not in source
    assert "place_order" not in source
