from autotrader.capital_ledger import PillarEquity, reconcile_pillars
from autotrader.portfolio_ledger import PortfolioLedger


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


def test_pillar_day_start_equity_is_restart_safe_and_immutable(tmp_path):
    path = tmp_path / "portfolio.db"
    ledger = PortfolioLedger(path)
    ledger.save_pillar_day_start_equity(
        pillar="alpaca_crypto", equity_date="2026-08-28", timezone="UTC",
        day_start_timestamp="2026-08-28T00:00:00+00:00",
        starting_economic_equity=795.59, source="provider_reconciled_open",
    )
    ledger.save_pillar_day_start_equity(
        pillar="alpaca_crypto", equity_date="2026-08-28", timezone="UTC",
        day_start_timestamp="2026-08-28T01:00:00+00:00",
        starting_economic_equity=999.0, source="incorrect_restart",
    )
    restored = PortfolioLedger(path).load_pillar_day_start_equity(
        pillar="alpaca_crypto", equity_date="2026-08-28"
    )
    assert restored["starting_economic_equity"] == 795.59
    assert restored["day_start_timestamp"] == "2026-08-28T00:00:00+00:00"
