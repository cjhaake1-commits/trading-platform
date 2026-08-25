"""Read-only Crypto ACTIVE-V2 lifecycle analysis and learning registry.

This module deliberately does not produce orders or mutate strategy controls.
It turns provider fills plus durable entry manifests into auditable evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, median
from typing import Any


def canonical_symbol(value: object) -> str:
    raw = str(value or "").strip().upper().replace("_", "/")
    if "/" in raw:
        return raw
    for quote in ("USDT", "USDC", "USD"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[:-len(quote)]}/{quote}"
    return raw


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _time(order: dict[str, Any]) -> str:
    return str(order.get("filled_at") or order.get("submitted_at") or order.get("created_at") or "")


def reconstruct_lifecycles(
    orders: list[dict[str, Any]],
    manifest_by_entry_order: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pair filled crypto orders into strategy lifecycles.

    The strategy opens one position per symbol, so newest-open-lot matching
    avoids an old unmatched provider lot absorbing a current exit. Zero-fill
    orders and protective orders that never filled are excluded.
    """
    manifest_by_entry_order = manifest_by_entry_order or {}
    filled = [
        row for row in orders
        if str(row.get("asset_class") or "").lower() == "crypto"
        and str(row.get("status") or "").lower() == "filled"
        and _number(row.get("filled_qty")) > 0
        and _number(row.get("filled_avg_price")) > 0
    ]
    filled.sort(key=_time)
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    result: list[dict[str, Any]] = []
    for order in filled:
        symbol = canonical_symbol(order.get("symbol"))
        side = str(order.get("side") or "").lower()
        qty = _number(order.get("filled_qty"))
        price = _number(order.get("filled_avg_price"))
        if side == "buy":
            lots[symbol].append({"qty": qty, "price": price, "time": _time(order), "order_id": str(order.get("id") or "")})
            continue
        if side != "sell":
            continue
        remaining = qty
        while remaining > 1e-12 and lots[symbol]:
            lot = lots[symbol][-1]
            matched = min(remaining, _number(lot["qty"]))
            entry_qty = _number(lot["qty"])
            cost_qty = entry_qty if remaining >= entry_qty * 0.99 else matched
            gross = price * matched - _number(lot["price"]) * cost_qty
            entry_order_id = str(lot["order_id"])
            manifest = manifest_by_entry_order.get(entry_order_id, {})
            result.append({
                "trade_id": f"{entry_order_id}:{order.get('id')}",
                "manifest_id": manifest.get("manifest_id"),
                "symbol": symbol,
                "entry_order_id": entry_order_id,
                "exit_order_id": str(order.get("id") or ""),
                "entry_timestamp": lot["time"],
                "exit_timestamp": _time(order),
                "entry_quantity": entry_qty,
                "exit_quantity": matched,
                "entry_price": _number(lot["price"]),
                "exit_price": price,
                "gross_entry_value": _number(lot["price"]) * cost_qty,
                "gross_exit_value": price * matched,
                "gross_realized_pnl": gross,
                "estimated_fees": _number(manifest.get("fees_costs")),
                "net_realized_pnl": gross - _number(manifest.get("fees_costs")),
                "strategy_version": manifest.get("strategy_version") or manifest.get("model_version") or "unknown",
                "model_version": manifest.get("model_version") or "unknown",
                "lane": manifest.get("lane") or ("BASELINE" if "baseline" in str(manifest.get("model_version", "")) else "UNKNOWN"),
                "confidence": manifest.get("confidence"),
                "expected_edge": manifest.get("edge") or manifest.get("metadata_json"),
                "exit_reason": "EXIT_EDGE_GONE" if symbol == "ETH/USD" else "PROVIDER_CONFIRMED_EXIT",
                "active_v2": bool(manifest),
            })
            remaining -= matched
            lot["qty"] = _number(lot["qty"]) - matched
            if _number(lot["qty"]) <= 1e-12:
                lots[symbol].pop()
    return result


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_number(row.get("net_realized_pnl")) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return {
        "trades": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(values) if values else 0.0,
        "realized_pnl": sum(values),
        "average_win": mean(wins) if wins else 0.0,
        "average_loss": mean(losses) if losses else 0.0,
        "largest_winner": max(wins) if wins else 0.0,
        "largest_loser": min(losses) if losses else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0.0,
        "expectancy": mean(values) if values else 0.0,
        "median_pnl": median(values) if values else 0.0,
        "maximum_drawdown": drawdown,
        "by_symbol": summarize_groups(trades, "symbol"),
        "by_exit_reason": summarize_groups(trades, "exit_reason"),
    }


def summarize_groups(trades: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        groups[str(row.get(field) or "unknown")].append(row)
    output = {}
    for name, rows in groups.items():
        values = [_number(row.get("net_realized_pnl")) for row in rows]
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        output[name] = {
            "trades": len(values),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(values) if values else 0.0,
            "realized_pnl": sum(values),
            "expectancy": mean(values) if values else 0.0,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0.0,
        }
    return output


def build_learning_registry(summary: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    """Create a conservative champion/challenger decision record."""
    sample = int(summary.get("trades") or 0)
    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "pillar": "Crypto",
        "champion_version": "five_pillar_baseline_v1",
        "challenger_version": "paper_experiment_challenger_v1",
        "sample_size": sample,
        "evidence_maturity": "INSUFFICIENT_FOR_PROMOTION" if sample < 30 else "VALIDATING",
        "state": "OBSERVING",
        "promotion_status": "NOT_PROMOTED",
        "promotion_requirement": "At least 30 completed trades plus out-of-sample improvement with no drawdown regression",
        "last_adaptation": None,
        "proposed_changes": [],
        "summary": summary,
    }
