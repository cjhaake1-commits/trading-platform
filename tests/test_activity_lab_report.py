from autotrader.paper_experiment import PaperExperimentLedger
from scripts.create_activity_lab_report import _ledger_summary, _safety_snapshot


def test_activity_report_exposes_full_funnel_without_inventing_provider_stages(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Crypto", engine="crypto", provider="paper", market="BTC/USD",
        strategy="MOMENTUM", strategy_version="v1", model_version="v1", features={},
        candidate_status="SIGNAL", qualification_result="NO_TRADE", estimated_edge=None,
        expected_value=None,
    )
    summary = _ledger_summary(tmp_path / "experiment.db")
    funnel = summary["Crypto"]["funnel"]
    assert set(funnel) == {"UNIVERSE", "DATA_VALID", "LIQUID", "SPREAD_VALID", "CANDIDATES", "SIGNALS", "POSITIVE_EDGE_OR_PROXY", "RISK_APPROVED", "CAPITAL_APPROVED", "QUALIFIED", "ACTUAL", "SHADOW", "ORDERS", "FILLS", "EXITS", "LEARNING"}
    assert funnel["CANDIDATES"] == 1
    assert funnel["SIGNALS"] == 1
    assert funnel["LIQUID"] == "UNKNOWN"
    assert summary["Crypto"]["bottlenecks"] == []


def test_activity_report_classifies_observed_bottlenecks(tmp_path):
    ledger = PaperExperimentLedger(tmp_path / "experiment.db")
    ledger.record_activity(
        experiment_id="E1", pillar="Crypto", engine="crypto", provider="paper", market="BTC/USD",
        strategy="MOMENTUM", strategy_version="v1", model_version="v1", features={},
        candidate_status="REJECTED", qualification_result="NO_TRADE", rejection_reason="NO_EDGE",
    )
    bottleneck = _ledger_summary(tmp_path / "experiment.db")["Crypto"]["bottlenecks"][0]
    assert bottleneck["classification"] == "OPTIMIZABLE"
    assert bottleneck["impact_pct"] == 100.0


def test_activity_report_safety_snapshot_is_paper_only():
    assert _safety_snapshot() == {
        "mode": "paper",
        "live_trading_enabled": False,
        "real_money_orders": 0,
        "execution_policy": "paper/simulation/demo only",
    }
