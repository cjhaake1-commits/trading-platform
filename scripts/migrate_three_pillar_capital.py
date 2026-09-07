from __future__ import annotations

from autotrader.capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL, pillar_for_asset
from autotrader.models import PortfolioState
from autotrader.portfolio_ledger import PortfolioLedger
from datetime import UTC, datetime
import sqlite3

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
    # Migrate only the active non-Kalshi day-start accounting baselines.  These
    # are persisted state, not risk limits; leaving the old $1,000 rows in
    # place makes fresh allocation/accounting reports understate capacity.
    day = datetime.now(UTC).date().isoformat()
    for pillar, allocation in PILLAR_ALLOCATIONS.items():
        ledger.save_pillar_day_start_equity(
            pillar=pillar,
            equity_date=day,
            timezone="UTC",
            day_start_timestamp=f"{day}T00:00:00+00:00",
            starting_economic_equity=allocation,
            source="authorized_paper_capital_migration",
        )
        # Existing rows are intentionally immutable during normal runtime,
        # but this explicit one-time migration must repair the stale baseline.
        with sqlite3.connect(LEDGER_PATH) as connection:
            connection.execute(
                "UPDATE pillar_day_start_equity SET starting_economic_equity=?, source=?, persisted_at=? WHERE pillar=? AND equity_date=?",
                (float(allocation), "authorized_paper_capital_migration", datetime.now(UTC).isoformat(), pillar, day),
            )
    exposure = {name: 0.0 for name in PILLAR_ALLOCATIONS}
    for position in portfolio.positions.values():
        exposure[pillar_for_asset(position.asset_class)] += abs(position.quantity * position.average_price)
    print({
        "ok": True,
        "total_paper_capital": TOTAL_PAPER_CAPITAL,
        "pillar_allocations": PILLAR_ALLOCATIONS,
        "current_exposure": exposure,
        "note": (
            "Existing positions preserved. Pillars already above $1,000 receive no "
            "new exposure until capacity is available."
        ),
    })


if __name__ == "__main__":
    main()
