from __future__ import annotations

from autotrader.capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL, pillar_for_asset
from autotrader.models import PortfolioState
from autotrader.portfolio_ledger import PortfolioLedger

LEDGER_PATH = "var/autotrader/portfolio.db"


def main() -> None:
    ledger = PortfolioLedger(LEDGER_PATH)
    loaded = ledger.load_portfolio()
    if loaded is None:
        portfolio = PortfolioState(TOTAL_PAPER_CAPITAL, TOTAL_PAPER_CAPITAL)
    else:
        old, _peak = loaded
        # Preserve positions and accumulated P&L. Add the new $1,000 crypto sleeve
        # to the logical capital base rather than erasing trading history.
        portfolio = PortfolioState(
            equity=TOTAL_PAPER_CAPITAL + old.daily_pnl,
            cash=TOTAL_PAPER_CAPITAL + old.daily_pnl,
            daily_pnl=old.daily_pnl,
            weekly_pnl=old.weekly_pnl,
            positions=old.positions,
        )
    ledger.save_portfolio(portfolio, peak_equity=max(TOTAL_PAPER_CAPITAL, portfolio.equity))
    exposure = {name: 0.0 for name in PILLAR_ALLOCATIONS}
    for position in portfolio.positions.values():
        exposure[pillar_for_asset(position.asset_class)] += abs(position.quantity * position.average_price)
    print({
        "ok": True,
        "total_paper_capital": TOTAL_PAPER_CAPITAL,
        "pillar_allocations": PILLAR_ALLOCATIONS,
        "current_exposure": exposure,
        "note": "Existing positions preserved. Pillars already above $1,000 receive no new exposure until capacity is available.",
    })


if __name__ == "__main__":
    main()
