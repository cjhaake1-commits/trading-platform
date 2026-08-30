"""Point-in-time corporate feature derivation from normalized SEC facts."""
from __future__ import annotations

from typing import Mapping


def derive_features(facts: Mapping[str, object], *, effective_at: str, version: str = "corporate-v1") -> dict[str, object]:
    def number(name: str) -> float | None:
        value = facts.get(name)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    revenue, gross, operating, net, cash, debt = (number(x) for x in ("revenue", "gross_profit", "operating_income", "net_income", "cash", "debt"))
    result: dict[str, object] = {"effective_at": effective_at, "feature_version": version, "data_quality": "PARTIAL"}
    if revenue and gross is not None:
        result["gross_margin"] = gross / revenue
    if revenue and operating is not None:
        result["operating_margin"] = operating / revenue
    if revenue and net is not None:
        result["net_margin"] = net / revenue
    if cash is not None and debt not in (None, 0):
        result["cash_debt"] = cash / debt
    if result.keys() - {"effective_at", "feature_version", "data_quality"}:
        result["data_quality"] = "VALID"
    return result
