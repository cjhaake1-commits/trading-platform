from autotrader.capital_ledger import PillarEquity, reconcile_pillars


def test_six_pillar_equity_and_allocation_invariants():
    rows = [
        PillarEquity(name, 1000.0, 1000.0 - deployed - pending + realized, deployed, deployed + unrealized, pending, realized, unrealized)
        for name, deployed, pending, realized, unrealized in (
            ("Stocks", 100.0, 0.0, 2.0, 3.0), ("Forex", 0.0, 0.0, 0.0, 0.0),
            ("Crypto", 0.0, 0.0, 0.0, 0.0), ("Metals/Commodities", 0.0, 0.0, 0.0, 0.0),
            ("International", 0.0, 0.0, 0.0, 0.0), ("Kalshi", 0.0, 0.0, 0.0, 0.0),
        )
    ]
    report = reconcile_pillars(rows)
    assert report["starting_capital"] == 6000.0
    assert report["equity"] == 6005.0
    assert report["invariant"] is True
    assert report["allocation_invariant"] is True
