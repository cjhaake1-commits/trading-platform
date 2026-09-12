import pytest

from autotrader.forward_evidence import ForwardEvidenceLedger, readiness_report


def _row(**extra):
    row = {
        "decision_id": "d1",
        "decision_ts": "2026-09-02T10:00:00+00:00",
        "pillar": "Crypto",
        "engine": "paper",
        "provider": "Alpaca Paper",
        "instrument": "BTC/USD",
        "strategy": "x",
        "strategy_version": "v1",
        "model_version": "m1",
        "scope": "FORWARD_PAPER",
        "data_timestamp": "2026-09-02T09:59:00+00:00",
        "feature_timestamp": "2026-09-02T09:59:30+00:00",
        "learning_evidence_timestamp": "2026-09-02T09:58:00+00:00",
    }
    row.update(extra)
    return row


def test_forward_ledger_is_append_only(tmp_path):
    ledger = ForwardEvidenceLedger(tmp_path / "f.db")
    assert ledger.append(_row()) == "d1"
    assert ledger.append(_row()) == "d1"


def test_provenance_rejects_lookahead(tmp_path):
    with pytest.raises(ValueError):
        ForwardEvidenceLedger(tmp_path / "f.db").append(_row(data_timestamp="2026-09-02T10:01:00+00:00"))


def test_readiness_has_no_live_authority():
    assert (
        readiness_report(sample_size=1, minimum_sample=30, expectancy=1, drawdown=0, integrity_ok=True)["state"]
        == "INSUFFICIENT_DATA"
    )
