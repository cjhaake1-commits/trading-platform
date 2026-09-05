from autotrader.performance_truth import report


def test_performance_truth_keeps_unrealized_out_of_forward_metrics(tmp_path):
    from autotrader.forward_evidence import ForwardEvidenceLedger
    ledger = ForwardEvidenceLedger(tmp_path / "evidence.db")
    assert report(portfolio={"economic_capital": 100, "realized_pnl": 2, "unrealized_pnl": -9}, ledger=ledger)["clean_forward"]["state"] == "INSUFFICIENT_DATA"


def test_performance_truth_reports_clean_forward_metrics_only(tmp_path):
    from autotrader.forward_evidence import ForwardEvidenceLedger
    ledger = ForwardEvidenceLedger(tmp_path / "evidence.db")
    row = {"decision_id":"d1","decision_ts":"2026-09-02T10:00:00+00:00","pillar":"Stocks","engine":"autonomous-paper-trading","provider":"Alpaca","instrument":"SPY","strategy":"s","strategy_version":"v1","model_version":"m","scope":"FORWARD_PAPER","realized_pnl":10,"capital_required":100}
    ledger.append(row)
    result = report(portfolio={"economic_capital":1000,"realized_pnl":999,"unrealized_pnl":-2}, ledger=ledger)["clean_forward"]
    assert result["trade_count"] == 1 and result["wins"] == 1
    assert result["return_on_deployed_capital"] == .1
