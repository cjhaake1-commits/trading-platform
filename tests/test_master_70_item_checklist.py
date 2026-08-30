import importlib.util
from pathlib import Path


def _module():
    spec = importlib.util.spec_from_file_location("master_checklist", Path("scripts/create_master_70_item_checklist.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_master_checklist_has_seventy_unique_items():
    module = _module()
    assert len(module.ITEMS) == 70
    assert len({item_id for item_id, _ in module.ITEMS}) == 70


def test_checklist_does_not_promote_missing_evidence(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.chdir(tmp_path)
    result = module.build_checklist()
    assert len(result["items"]) == 70
    assert result["all_pass"] is False
    assert all(item["status"] in {"PASS", "UNKNOWN", "FAIL"} for item in result["items"])
