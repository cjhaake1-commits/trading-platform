from autotrader.performance_truth import report


def test_performance_truth_keeps_unrealized_out_of_forward_metrics(tmp_path):
    from autotrader.forward_evidence import ForwardEvidenceLedger
    ledger = ForwardEvidenceLedger(tmp_path / "evidence.db")
    assert report(portfolio={"economic_capital": 100, "realized_pnl": 2, "unrealized_pnl": -9}, ledger=ledger)["clean_forward"]["state"] == "INSUFFICIENT_DATA"
