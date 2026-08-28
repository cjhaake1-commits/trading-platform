from autotrader.edge_engine import (
    AccountingSnapshot,
    benchmark_metrics,
    classify_edge,
    crypto_churn_state,
    verified_outcomes,
)


def test_accounting_snapshot_requires_cash_identity():
    snapshot = AccountingSnapshot("Crypto", 1000, 1000, 795.59, 0, 0, 0, -204.41, 0, 0, "alpaca")
    assert snapshot.verify()["accounting_status"] == "ACCOUNTING_VERIFIED"
    assert snapshot.daily_return < 0


def test_benchmarks_and_edge_use_verified_records_only():
    rows = [{"accounting_status": "ACCOUNTING_VERIFIED", "realized_pnl": 2.0} for _ in range(30)]
    rows.append({"accounting_status": "ACCOUNTING_UNVERIFIED", "realized_pnl": 9999.0})
    metrics = benchmark_metrics(rows, benchmark_return=0.01, starting_equity=100)
    assert len(verified_outcomes(rows)) == 30
    assert metrics["sample_size"] == 30
    assert classify_edge(metrics) == "EDGE_EMERGING"


def test_crypto_churn_detects_repeated_short_lifecycles():
    rows = [{"symbol": "BTC/USD", "net_realized_pnl": -1.0, "holding_seconds": 60} for _ in range(20)]
    report = crypto_churn_state(rows)
    assert report["state"] == "CHURN_DETECTED"
    assert report["repeat_entry_pnl"] == -20.0
