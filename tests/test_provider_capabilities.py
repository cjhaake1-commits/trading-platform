from autotrader.provider_capabilities import Capability, capability_matrix


def test_capability_matrix_preserves_state_and_reason(tmp_path):
    rows = capability_matrix([Capability("Alpaca", "PAPER", "OPTIONS", "UNKNOWN", "adapter has no options probe")], tmp_path / "caps.json")
    assert rows[0]["state"] == "UNKNOWN"
    assert "probe" in rows[0]["reason"]
