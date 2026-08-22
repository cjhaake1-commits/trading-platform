"""Paper short-candidate gates; no broker submission occurs here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortCheck:
    allowed: bool
    reason: str


def evaluate_paper_short(*, environment: str, shortable: bool, borrow_available: bool | None, liquidity_ok: bool, spread_ok: bool, session_open: bool, same_symbol_conflict: bool, available_capital: float, required_capital: float, risk_approved: bool) -> ShortCheck:
    checks = ((environment.upper() == "PAPER", "paper environment required"), (shortable, "instrument is not shortable"), (borrow_available is not False, "borrow unavailable"), (liquidity_ok, "liquidity rejected"), (spread_ok, "spread rejected"), (session_open, "market session closed"), (not same_symbol_conflict, "same-symbol conflict"), (available_capital >= required_capital, "pillar cap exhausted"), (risk_approved, "risk rejected"))
    for passed, reason in checks:
        if not passed:
            return ShortCheck(False, reason)
    return ShortCheck(True, "paper short candidate passed safety gates")
