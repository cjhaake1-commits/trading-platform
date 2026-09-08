"""Read-only income-learning measurements; never an order or promotion signal."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from .capital_allocations import CAPITAL_POLICY_ID, SIX_PILLAR_BASE_CAPITAL


RESEARCH_FAMILIES = (
    "INTRADAY_MOMENTUM", "OPENING_RANGE_BREAKOUT", "VWAP_REVERSION",
    "FX_SESSION_TRADING", "CRYPTO_INTRADAY", "ELIGIBLE_EQUITY_SHORTS",
    "EVENT_DRIVEN", "COST_AWARE_SCALPING", "LIQUIDITY_PROVISION_RESEARCH",
    "OPTIONS_RESEARCH_CAPABILITY_GATED",
)


def income_learning_contract() -> dict[str, object]:
    return {
        "objective": "NET_REALIZED_INCOME_WITH_CAPITAL_RECYCLING",
        "capital_policy_id": CAPITAL_POLICY_ID,
        "initial_economic_capital": SIX_PILLAR_BASE_CAPITAL,
        "long_term_portfolio_mandate": False,
        "research_families": list(RESEARCH_FAMILIES),
        "live_authorization": False,
        "force_utilization": False,
        "automatic_strategy_promotion": False,
        "required_costs": ["fees", "spread", "slippage", "borrow", "financing", "funding"],
        "operating_costs": ["market_data", "compute", "model_inference"],
        "note": "Research coverage is not evidence of data ingestion or execution support.",
    }


def _number(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _timestamp(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo is not None else None


def summarize_income_outcomes(outcomes: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Measure cost-verified, natural, closed cycles in the restored $6k cohort.

    Monetary results are decimal strings to retain sub-cent precision. Net P&L
    must already include costs: do not subtract embedded spread/slippage twice.
    Cash released includes principal and is NEVER treated as profit. Missing
    evidence remains unknown. This does not replace total-equity accounting.
    """
    rows = [dict(row) for row in outcomes]
    counts: Counter[str] = Counter()
    by_id: dict[str, dict[str, object]] = {}
    conflicts: set[str] = set()
    for row in rows:
        key = str(row.get("outcome_id") or "")
        if not key:
            counts["MISSING_OUTCOME_ID"] += 1
        elif key in by_id:
            counts["DUPLICATE_RECORD"] += 1
            if row != by_id[key]:
                conflicts.add(key)
        else:
            by_id[key] = row
    groups: dict[tuple[str, ...], dict[str, object]] = {}
    accepted = 0
    for key, row in by_id.items():
        reason = None
        if key in conflicts:
            reason = "CONFLICTING_OUTCOME"
        elif row.get("capital_policy_id") != CAPITAL_POLICY_ID:
            reason = "OTHER_OR_UNVERSIONED_CAPITAL_COHORT"
        elif row.get("execution_mode") not in {"PAPER", "PRACTICE", "SIM", "DEMO"}:
            reason = "NOT_CONFIRMED_SIMULATED"
        elif row.get("ownership") != "PLATFORM_OWNED" or row.get("origin") != "NATURAL":
            reason = "NOT_NATURAL_PLATFORM_OWNED"
        elif row.get("entry_fill_confirmed") is not True or row.get("exit_fill_confirmed") is not True:
            reason = "MISSING_PROVIDER_FILL_PROOF"
        elif row.get("costs_complete") is not True:
            reason = "COSTS_NOT_VERIFIED"
        elif any(not row.get(field) for field in ("pillar", "strategy", "strategy_version", "provider", "entry_provider_order_id", "exit_provider_order_id")):
            reason = "MISSING_ATTRIBUTION"
        pnl = _number(row.get("net_realized_pnl"))
        capital = _number(row.get("allocated_capital"))
        released = _number(row.get("capital_released"))
        entered = _timestamp(row.get("entry_fill_at"))
        exited = _timestamp(row.get("exit_fill_at"))
        if not reason and (
            pnl is None or capital is None or capital <= 0 or released is None or released < 0
            or entered is None or exited is None or exited <= entered
        ):
            reason = "MISSING_OR_INVALID_ECONOMICS"
        if reason:
            counts[reason] += 1
            continue
        assert pnl is not None and capital is not None and released is not None
        assert entered is not None and exited is not None
        duration = Decimal(str((exited - entered).total_seconds())) / Decimal(3600)
        group_key = tuple(str(row[field]) for field in (
            "pillar", "strategy", "strategy_version", "provider", "execution_mode"
        )) + (exited.date().isoformat(),)
        group = groups.setdefault(group_key, {
            "pillar": group_key[0], "strategy": group_key[1], "strategy_version": group_key[2],
            "provider": group_key[3], "execution_mode": group_key[4], "exit_date_utc": group_key[5],
            "closed_cycles": 0, "wins": 0, "losses": 0,
            "net_realized_pnl": Decimal(0), "capital_released": Decimal(0),
            "capital_hours": Decimal(0), "holding_hours": Decimal(0),
        })
        group["closed_cycles"] += 1
        group["wins"] += int(pnl > 0)
        group["losses"] += int(pnl < 0)
        group["net_realized_pnl"] += pnl
        group["capital_released"] += released
        group["capital_hours"] += capital * duration
        group["holding_hours"] += duration
        accepted += 1
    output = []
    for _, group in sorted(groups.items()):
        group["average_net_pnl_per_cycle"] = group["net_realized_pnl"] / group["closed_cycles"]
        group["net_pnl_per_capital_hour"] = group["net_realized_pnl"] / group["capital_hours"]
        output.append({k: str(v) if isinstance(v, Decimal) else v for k, v in group.items()})
    net_total = sum((Decimal(group["net_realized_pnl"]) for group in output), Decimal(0))
    return {
        "contract": income_learning_contract(), "read_only": True,
        "status": "MEASURED_NOT_VALIDATED" if accepted else "INSUFFICIENT_INCOME_EVIDENCE",
        "input_records": len(rows), "qualified_closed_cycles": accepted,
        "exclusions": dict(counts), "per_strategy_day": output,
        "net_realized_pnl": str(net_total) if accepted else None,
        "account_total_equity_pnl": None,
        "withdrawable_income": None,
        "capital_redeployed": None,
        "limitations": [
            "Open-position losses and reconciled account equity must also be reviewed.",
            "Released principal is not income; redeployment requires a linked subsequent entry.",
            "Withdrawal capacity requires settled funds, margin headroom, and operating costs.",
            "No strategy is promoted by turnover, win rate, or this report alone.",
        ],
    }
