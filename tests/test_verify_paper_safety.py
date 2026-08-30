import json

import pytest

from scripts.verify_paper_safety import verify


def test_paper_safety_accepts_paper_and_demo_snapshots(tmp_path):
    paths = []
    for index, payload in enumerate((
        {"live_trading_enabled": False, "execution_state": "armed_paper"},
        {"environment": "demo", "real_money_orders": 0},
    )):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps(payload))
        paths.append(str(path))
    result = verify(tuple(paths))
    assert result["safe"] is True


@pytest.mark.parametrize("payload", [
    {"live_trading_enabled": True},
    {"environment": "live"},
    {"real_money_orders": 1},
])
def test_paper_safety_rejects_unsafe_evidence(tmp_path, payload):
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(payload))
    result = verify((str(path),))
    assert result["safe"] is False
