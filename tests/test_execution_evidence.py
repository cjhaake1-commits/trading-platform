import pytest

from autotrader.execution_evidence import persist_execution_evidence


def test_provider_native_requires_real_provider_id(tmp_path):
    with pytest.raises(ValueError):
        persist_execution_evidence({"provider": "Alpaca", "environment": "PAPER", "proof_type": "PROVIDER_NATIVE_ORDER"}, tmp_path / "r.db")


def test_sim_id_cannot_masquerade_as_provider_order(tmp_path):
    with pytest.raises(ValueError):
        persist_execution_evidence({"provider": "Alpaca", "environment": "PAPER", "proof_type": "PROVIDER_NATIVE_ORDER", "provider_order_id": "SIM-1"}, tmp_path / "r.db")
