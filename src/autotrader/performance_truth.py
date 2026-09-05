"""Separate current portfolio economics from clean forward evidence."""
from __future__ import annotations

from typing import Mapping
from .forward_evidence import ForwardEvidenceLedger


def report(*, portfolio: Mapping[str, object], ledger: ForwardEvidenceLedger | None = None) -> dict[str, object]:
    evidence = (ledger or ForwardEvidenceLedger()).metrics("FORWARD_PAPER")
    capital = float(portfolio.get("economic_capital", portfolio.get("equity", 0)) or 0)
    realized = float(portfolio.get("realized_pnl", 0) or 0)
    unrealized = float(portfolio.get("unrealized_pnl", 0) or 0)
    return {"current_portfolio": {"economic_capital": capital,
            "economic_equity": float(portfolio.get("economic_equity", capital + realized + unrealized) or 0),
            "realized_pnl": realized, "unrealized_pnl": unrealized,
            "total_pnl": realized + unrealized,
            "total_return": (realized + unrealized) / capital if capital else None},
            "clean_forward": {"sample_size": evidence["completed"],
            "realized_pnl": evidence["realized_pnl"], "win_rate": evidence["win_rate"],
            "expectancy": evidence["expectancy_after_costs"], "profit_factor": evidence["profit_factor"],
            "max_drawdown": evidence["max_drawdown"],
            "state": "INSUFFICIENT_DATA" if not evidence["completed"] else "EVIDENCE_AVAILABLE"}}
