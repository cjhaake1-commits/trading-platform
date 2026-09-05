"""Currency-level exposure aggregation for OANDA practice candidates."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


def currency_exposure(positions: Iterable[Mapping[str, object]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for position in positions:
        pair = str(position.get("instrument") or position.get("symbol") or "").replace("/", "_").upper()
        base, sep, quote = pair.partition("_")
        if not sep or not base or not quote:
            continue
        units = float(position.get("units") or position.get("quantity") or 0.0)
        side = str(position.get("side") or "LONG").upper()
        sign = -1.0 if side == "SHORT" else 1.0
        notional = abs(float(position.get("notional") or units))
        totals[base] += sign * notional
        totals[quote] -= sign * notional
    return dict(sorted(totals.items()))


def pair_gate(*, pair: str, proposed_notional: float, existing: Iterable[Mapping[str, object]], max_currency_exposure: float) -> dict[str, object]:
    current = currency_exposure(existing)
    base, _, quote = pair.replace("/", "_").upper().partition("_")
    if not base or not quote or proposed_notional <= 0:
        return {"approved": False, "reason": "INVALID_PAIR_OR_NOTIONAL", "exposure": current}
    if abs(current.get(base, 0.0) + proposed_notional) > max_currency_exposure or abs(current.get(quote, 0.0) - proposed_notional) > max_currency_exposure:
        return {"approved": False, "reason": "CURRENCY_CONCENTRATION", "exposure": current}
    return {"approved": True, "reason": "CURRENCY_CONCENTRATION_ALLOWED", "exposure": current}
