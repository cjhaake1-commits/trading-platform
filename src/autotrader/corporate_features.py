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
    def ratio(name: str, denominator: float | None, output: str) -> None:
        value = number(name)
        if value is not None and denominator not in (None, 0):
            result[output] = value / denominator
    ratio("operating_cash_flow", revenue, "cash_conversion")
    ratio("free_cash_flow", revenue, "fcf_margin")
    ratio("capex", revenue, "capex_intensity")
    ratio("inventory", revenue, "inventory_revenue")
    ratio("receivables", revenue, "receivables_revenue")
    if cash is not None and debt is not None:
        result["net_debt"] = debt - cash
    current_assets, current_liabilities = number("current_assets"), number("current_liabilities")
    if current_assets is not None and current_liabilities not in (None, 0):
        result["current_ratio"] = current_assets / current_liabilities
        result["working_capital"] = current_assets - current_liabilities
    assets = number("assets")
    ratio("net_income", assets, "roa")
    equity = number("equity")
    ratio("net_income", equity, "roe")
    prior_revenue = number("prior_revenue")
    if revenue is not None and prior_revenue not in (None, 0):
        result["revenue_growth"] = revenue / prior_revenue - 1.0
    prior_margin = number("prior_operating_margin")
    if "operating_margin" in result and prior_margin is not None:
        result["margin_change"] = float(result["operating_margin"]) - prior_margin
    if result.keys() - {"effective_at", "feature_version", "data_quality"}:
        result["data_quality"] = "VALID"
    return result
