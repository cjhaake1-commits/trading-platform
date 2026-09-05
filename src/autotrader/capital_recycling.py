"""Fail-closed position lifecycle accounting for paper capital recycling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RecyclingDecision:
    instrument: str
    action: str
    reason: str
    released_capital: float = 0.0
    realized_pnl: float | None = None


def evaluate_position(position: Mapping[str, object], *, replacement_score: float | None = None,
                      current_score: float | None = None) -> RecyclingDecision:
    """Evaluate only explicit, authoritative exit signals; never infer an exit."""
    instrument = str(position.get("instrument") or position.get("symbol") or "UNKNOWN")
    ownership = str(position.get("ownership") or "UNKNOWN").upper()
    if ownership != "PLATFORM_OWNED":
        return RecyclingDecision(instrument, "PROTECTED", "OWNERSHIP_NOT_PLATFORM_OWNED")
    signal = str(position.get("exit_signal") or "HOLD").upper()
    allowed = {"TAKE_PROFIT", "STOP", "TRAILING_EXIT", "TIME_EXIT", "THESIS_INVALIDATION", "RISK_REDUCTION"}
    if signal in allowed:
        released = float(position.get("capital_released") or position.get("market_value") or 0.0)
        pnl = position.get("realized_pnl")
        return RecyclingDecision(instrument, signal, "EXPLICIT_AUTHORIZED_EXIT", max(released, 0.0), float(pnl) if pnl is not None else None)
    if replacement_score is not None and current_score is not None and replacement_score > current_score:
        return RecyclingDecision(instrument, "REVIEW_REPLACEMENT", "REPLACEMENT_REQUIRES_EXISTING_RISK_APPROVAL")
    return RecyclingDecision(instrument, "HOLD", "NO_AUTHORIZED_EXIT_SIGNAL")


def summarize_releases(decisions: Sequence[RecyclingDecision]) -> dict[str, object]:
    exits = [item for item in decisions if item.action in {"TAKE_PROFIT", "STOP", "TRAILING_EXIT", "TIME_EXIT", "THESIS_INVALIDATION", "RISK_REDUCTION"}]
    pnl = [item.realized_pnl for item in exits if item.realized_pnl is not None]
    return {"evaluated": len(decisions), "exits": len(exits), "released_capital": sum(x.released_capital for x in exits),
            "realized_pnl": sum(pnl) if pnl else None, "execution_side_effects": "NONE"}
