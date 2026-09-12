import subprocess

from autotrader.reliability import (
    BoundedCircuit,
    credential_fingerprint,
    reconcile_with_recovery,
    supervise_services,
    validate_snapshot,
)


def test_secret_fingerprint_excludes_secret():
    assert credential_fingerprint({"HOST": "demo", "KEY": "a"}) == credential_fingerprint({"HOST": "demo", "KEY": "b"})


def test_circuit_opens_and_persists(tmp_path):
    c = BoundedCircuit(tmp_path / "state.json", max_attempts=2)
    c.failure("x", 1)
    row = c.failure("x", 2)
    assert row["circuit"] == "OPEN" and not c.allowed("x", 3)


def test_service_recovery_is_nontrading(tmp_path):
    class R:
        def __init__(self):
            self.calls = []

        def __call__(self, args, **kwargs):
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 0)

    r = R()
    assert supervise_services(("safe.service",), runner=r, circuit=BoundedCircuit(tmp_path / "s.json")) == []


def test_missing_read_is_not_zero():
    assert "MISSING_READ_COERCED_ZERO:X" in validate_snapshot(
        {
            "live_trading_enabled": False,
            "pillars": [{"pillar": "X", "provider_read_error": True, "economic_available": 0}],
        }
    )


def test_reconciliation_retries_and_recovers(tmp_path):
    calls = []

    def read():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError()
        return {"ownership": "preserved"}

    out = reconcile_with_recovery(
        read, lambda x: x["ownership"] == "preserved", circuit=BoundedCircuit(tmp_path / "r.json")
    )
    assert out["state"] == "RECOVERED" and out["trading_side_effects"] == "NONE"


def test_reconciliation_circuit_breaks(tmp_path):
    out = reconcile_with_recovery(
        lambda: (_ for _ in ()).throw(ConnectionError()),
        lambda _: True,
        circuit=BoundedCircuit(tmp_path / "r.json", max_attempts=2),
    )
    assert out["state"] == "RECONCILIATION_ERROR" and out["attempts"] == 2
