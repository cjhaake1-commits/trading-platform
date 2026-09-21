from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

import streamlit_app as core
from autotrader.international_trading import INTERNATIONAL_CURRENT_EPOCH

# Read-only observation board. No controls in this module may alter trading,
# allocation, execution, strategy, risk, credentials, or provider state.
# The board is read-only and refreshes through Streamlit's browser-safe reload
# hint; it never submits orders or mutates trading state.

PILLAR_ORDER = [
    "stocks",
    "Crypto",
    "Forex",
    "Metals / Commodities",
    "International",
    "Kalshi",
]
DISPLAY_NAMES = {
    "stocks": "Stocks / ETFs",
    "Metals / Commodities": "Metals / Commodities",
}
PILLAR_ALIASES = {
    "stocks": {"stocks", "Stocks", "US Stocks / ETFs", "US Stocks", "Stocks / ETFs", "Stocks/Crypto"},
    "Crypto": {"Crypto", "crypto"}, "Forex": {"Forex", "forex"},
    "Metals / Commodities": {"Metals / Commodities", "Metals/Commodities", "Metals", "metals"},
    "International": {"International", "international"}, "Kalshi": {"Kalshi", "kalshi"},
}
PILLAR_JOB_MAP = {
    "stocks": "autonomous-paper-trading",
    "Crypto": "autonomous-paper-trading",
    "Forex": "oanda-fx-paper-trading",
    "Metals / Commodities": "alpaca-metals-paper-trading",
    "International": "saxo-international-paper-trading",
}
BASE_CAPITAL = 1000.0
FUND_STARTING_CAPITAL = 6000.0
ANNUAL_GOAL = 250000.0
DAILY_CASH_FLOOR = 500.0
DAILY_CASH_STRETCH = 1000.0


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value):
    if value is None:
        return "UNAVAILABLE"
    return f"${f(value):,.2f}"


def signed_money(value):
    if value is None:
        return "UNAVAILABLE"
    value = f(value)
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def signed_pct(value):
    if value is None:
        return "UNAVAILABLE"
    value = f(value)
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"


def first_number(mapping, keys, default=0.0):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if mapping.get(key) is not None:
            try:
                return float(mapping[key])
            except (TypeError, ValueError):
                pass
    return default


def canonical_pillar(value):
    text = str(value or "").strip()
    for canonical, aliases in PILLAR_ALIASES.items():
        if text in aliases:
            return canonical
    return text


def _normalized_snapshot(snapshot):
    raw = snapshot.get("pillar_accounting_snapshot") if isinstance(snapshot, dict) else None
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return {}
    return {canonical_pillar(row.get("pillar")): row for row in raw if isinstance(row, dict)}


def _live_position_totals(live_positions):
    totals = {name: {"deployed": 0.0, "market_value": 0.0, "unrealized": 0.0, "positions": 0} for name in PILLAR_ORDER}
    for row in live_positions if isinstance(live_positions, list) else []:
        if not isinstance(row, dict):
            continue
        pillar = canonical_pillar(row.get("pillar"))
        if pillar not in totals:
            continue
        classification = str(row.get("classification") or "").upper()
        if classification and classification not in {"VALID_STRATEGY_POSITION", "ACTIVE V2"}:
            continue
        qty = abs(f(row.get("quantity")))
        avg = abs(f(row.get("average_price")))
        market_value = abs(f(row.get("market_value"), qty * avg))
        cost_basis = qty * avg if qty and avg else market_value
        totals[pillar]["deployed"] += cost_basis
        totals[pillar]["market_value"] += market_value
        totals[pillar]["unrealized"] += f(row.get("unrealized_pnl"))
        totals[pillar]["positions"] += 1
    return totals


def _saxo_live_truth():
    result = {
        "connected": False,
        "deployed": 0.0,
        "market_value": 0.0,
        "unrealized": 0.0,
        "positions": 0,
        "working_orders": 0,
        "trade_level": "",
        "error": "",
    }
    try:
        from autotrader.brokers.saxo_sim import SaxoSimAdapter

        adapter = SaxoSimAdapter.from_env()
        summary = adapter.account_summary()
        capabilities = adapter.session_capabilities()
        result["trade_level"] = str(capabilities.get("TradeLevel") or "")
        account_key = str(summary.default_account_key or "").strip()
        if not account_key:
            result["error"] = "Saxo SIM default account key unavailable"
            return result
        result["connected"] = True
        current_order_ids: set[str] = set()
        with sqlite3.connect("var/autotrader/international_trades.db") as connection:
            current_order_ids = {
                str(row[0]) for row in connection.execute(
                    "SELECT order_id FROM international_trades "
                    "WHERE allocation_epoch = ? AND status = 'executed' AND closed_at IS NULL",
                    (INTERNATIONAL_CURRENT_EPOCH,),
                ) if row[0]
            }
        result["legacy_positions"] = 0
        result["legacy_exposure"] = 0.0
        payload = adapter.list_positions(account_key=account_key)
        rows = payload.get("Data", []) if isinstance(payload, dict) else []
        result["provider_positions_raw"] = rows if isinstance(rows, list) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            base = row.get("PositionBase") if isinstance(row.get("PositionBase"), dict) else row
            view = row.get("PositionView") if isinstance(row.get("PositionView"), dict) else {}
            amount = abs(first_number(base, ["Amount"], 0.0))
            open_price = abs(first_number(base, ["OpenPrice"], 0.0))
            exposure = abs(first_number(view, ["Exposure"], 0.0))
            pnl = first_number(view, ["ProfitLossOnTrade"], 0.0)
            cost_basis = amount * open_price if amount and open_price else exposure
            source_order_id = str(base.get("SourceOrderId") or base.get("OrderId") or row.get("SourceOrderId") or row.get("OrderId") or "")
            if source_order_id in current_order_ids:
                result["deployed"] += cost_basis
                result["market_value"] += exposure if exposure else max(cost_basis + pnl, 0.0)
                result["unrealized"] += pnl
                result["positions"] += 1
            else:
                result["legacy_positions"] += 1
                result["legacy_exposure"] += exposure or max(cost_basis + pnl, 0.0)
        orders = adapter.list_orders(account_key=account_key)
        order_rows = orders.get("Data", []) if isinstance(orders, dict) else []
        result["working_orders"] = len(order_rows) if isinstance(order_rows, list) else 0
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _runtime_job_active(runtime, job_name):
    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    job = jobs.get(job_name) if isinstance(jobs.get(job_name), dict) else {}
    if not job:
        return False
    return (
        not bool(job.get("disabled"))
        and not bool(job.get("last_error"))
        and bool(job.get("last_started_at") or job.get("last_finished_at"))
    )


def _engine_active(name, runtime, live_state, kalshi, saxo_live):
    if name == "Kalshi":
        return (
            str(kalshi.get("connection") or "").startswith("CONNECTED")
            and str(kalshi.get("scanner") or "ACTIVE").upper() != "INACTIVE"
        )
    if name == "International":
        return bool(saxo_live.get("connected")) and _runtime_job_active(runtime, PILLAR_JOB_MAP[name])
    return bool(live_state.get("connected")) and _runtime_job_active(runtime, PILLAR_JOB_MAP[name])


def _exposure_state(engine_active, positions, working_orders):
    if not engine_active:
        return "ENGINE DEGRADED"
    if positions > 0:
        return "ACTIVE — POSITION OPEN"
    if working_orders > 0:
        return "ACTIVE — ORDER WORKING"
    return "ACTIVE — SEEKING EDGE"


def build_pillars(
    snapshot,
    runtime,
    live_status=None,
    kalshi=None,
    live_positions=None,
    saxo_live=None,
    crypto_realized_today=None,
    foundation_report=None,
):
    # Preserve the pre-six-pillar call shape used by integrations:
    # (snapshot, live_status, kalshi, live_positions, saxo_live).
    legacy_call = saxo_live is None and isinstance(live_positions, dict) and isinstance(kalshi, list)
    if legacy_call:
        saxo_live = live_positions
        live_positions = kalshi
        kalshi = live_status
        live_status = runtime
        runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    live_status = live_status if isinstance(live_status, dict) else {}
    kalshi = kalshi if isinstance(kalshi, dict) else {}
    live_positions = live_positions if isinstance(live_positions, list) else []
    saxo_live = saxo_live if isinstance(saxo_live, dict) else {}
    foundation_report = foundation_report if isinstance(foundation_report, dict) else {}
    foundation_pillars = foundation_report.get("pillars") if isinstance(foundation_report.get("pillars"), dict) else {}
    perf = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    normalized = _normalized_snapshot(snapshot)
    latest_cycle = snapshot.get("latest_cycle") if isinstance(snapshot.get("latest_cycle"), dict) else {}
    broker_totals = _live_position_totals(live_positions)
    rows = []
    for name in PILLAR_ORDER:
        n = normalized.get(name)
        # A ledger snapshot can be older than the direct provider read.  For
        # Crypto, force the live Alpaca path whenever it is connected so stale
        # persisted accounting cannot override current positions/orders/P&L.
        if name == "Crypto" and isinstance(live_status.get("Crypto"), dict) and live_status["Crypto"].get("connected"):
            n = None
        # An explicit failed provider read is authoritative too: never fall
        # back to a stale ledger/default cash value for Crypto.
        provider_failed = (
            name == "Crypto"
            and isinstance(live_status.get("Crypto"), dict)
            and live_status["Crypto"].get("connected") is False
        )
        if provider_failed:
            n = None
        if n is not None:
            status = str(n.get("accounting_status") or "ACCOUNTING_UNVERIFIED")
            realized = n.get("realized_today")
            unrealized = n.get("unrealized")
            total = n.get("total_pnl")
            rows.append({
                "name": name, "display": DISPLAY_NAMES.get(name, name),
                "engine_active": bool(n.get("provider_observed") and n.get("freshness") == "FRESH"),
                "provider_available": bool(n.get("provider_observed")),
                "state": "ACCOUNTING VERIFIED" if status == "ACCOUNTING_VERIFIED" else "VERIFYING",
                "equity": n.get("economic_equity"), "deployed": n.get("deployed_cash"),
                "pending": n.get("pending"), "available": n.get("available_cash"),
                "today_pnl": (f(realized, 0.0) + f(unrealized, 0.0)),
                "daily_return": n.get("daily_return"), "realized": realized,
                "unrealized": unrealized, "total_pnl": total,
                "positions": n.get("positions", 0), "working_orders": n.get("working_orders", 0),
                "completed_today": n.get("trades_today", 0), "activity_reason": n.get("reason", ""),
                "accounting_status": status, "freshness": n.get("freshness", "MISSING"),
            })
            continue
        p = perf.get(name) if isinstance(perf.get(name), dict) else {}
        if not p:
            p = next((perf.get(alias) for alias in PILLAR_ALIASES.get(name, {name}) if isinstance(perf.get(alias), dict)), {})
        state = live_status.get(name) if isinstance(live_status.get(name), dict) else {}
        if not state:
            state = next((live_status.get(alias) for alias in PILLAR_ALIASES.get(name, {name}) if isinstance(live_status.get(alias), dict)), {})
        broker = broker_totals.get(name, {})
        broker_positions = int(f(broker.get("positions")))
        working_orders = int(f(state.get("working_orders")))
        if name == "Crypto" and state.get("connected"):
            # Keep provider-reported dust/legacy holdings visible as positions
            # while strategy deployed capital remains based on owned positions.
            broker_positions = int(f(state.get("broker_positions"), broker_positions))

        if provider_failed:
            rows.append({
                "name": name, "display": DISPLAY_NAMES.get(name, name),
                "engine_active": False, "provider_available": False,
                "state": "UNAVAILABLE", "equity": None, "deployed": None,
                "pending": None, "available": None, "today_pnl": None,
                "daily_return": None, "realized": None, "unrealized": None,
                "total_pnl": None, "positions": None, "working_orders": None,
                "completed_today": 0, "activity_reason": str(state.get("error") or "Alpaca PAPER provider read failed"),
                "accounting_status": "ACCOUNTING_UNVERIFIED", "freshness": "ERROR",
            })
            continue

        if name == "Kalshi":
            deployed = first_number(kalshi, ["v2_deployed", "perps_deployed", "deployed"], 0.0)
            pending = first_number(kalshi, ["pending_capital", "pending"], 0.0)
            unrealized = first_number(kalshi, ["v2_unrealized_pnl", "perps_unrealized_pnl", "unrealized_pnl"], 0.0)
            realized = first_number(
                kalshi,
                ["v2_realized_pnl", "perps_realized_pnl", "realized_pnl"],
                first_number(p, ["net_generated_cash", "realized_pnl"], 0.0),
            )
            broker_positions = int(first_number(kalshi, ["perps_positions", "predictions_positions", "positions"], 0.0))
            working_orders = int(
                first_number(kalshi, ["perps_open_orders", "predictions_open_orders", "open_orders"], 0.0)
            )
        elif name == "International" and saxo_live.get("connected"):
            deployed = f(saxo_live.get("deployed"))
            pending = 0.0
            unrealized = f(saxo_live.get("unrealized"))
            realized = first_number(
                p, ["realized_today", "daily_realized_pnl", "net_generated_cash", "realized_pnl"], 0.0
            )
            broker_positions = int(f(saxo_live.get("positions")))
            working_orders = int(f(saxo_live.get("working_orders")))
        else:
            broker_deployed = f(broker.get("deployed"))
            deployed = (
                broker_deployed
                if broker_positions > 0
                else first_number(state, ["strategy_cost_basis", "strategy_deployed"], 0.0)
            )
            pending = first_number(state, ["pending_capital"], 0.0)
            broker_unrealized = f(broker.get("unrealized"))
            unrealized = (
                broker_unrealized
                if broker_positions > 0
                else first_number(state, ["unrealized_pnl"], first_number(p, ["unrealized_pnl"], 0.0))
            )
            realized = first_number(
                p, ["realized_today", "daily_realized_pnl", "net_generated_cash", "realized_pnl"], 0.0
            )

        # Alpaca's completed Crypto fills are reconstructed live by the
        # read-only board context.  They supersede the stale published
        # pillar aggregate for today's accounting only.
        if name == "Crypto" and crypto_realized_today is not None:
            realized = f(crypto_realized_today)

        completed_today = int(first_number(p, ["completed_trades_today", "completed_today", "completed_trades"], 0.0))
        today_pnl = first_number(p, ["today_pnl", "daily_pnl", "total_today", "realized_today"], realized + unrealized)
        total_pnl = first_number(p, ["total_pnl", "net_pnl", "net_generated_cash"], realized) + unrealized
        if name == "Crypto" and crypto_realized_today is not None:
            # The published Crypto aggregate may include stale or differently
            # scoped history.  Current economic equity must use the same
            # provider-reconstructed realized basis shown on this card.
            total_pnl = realized + unrealized
        equity = first_number(state, ["account_equity", "equity"], BASE_CAPITAL + total_pnl)
        available = max(equity - deployed - pending, 0.0)
        daily_return = today_pnl / BASE_CAPITAL if BASE_CAPITAL else 0.0
        engine_active = _engine_active(name, runtime, state, kalshi, saxo_live)
        exposure_state = _exposure_state(engine_active, broker_positions, working_orders)
        if name == "Crypto":
            state_name = "ACTIVE — SEEKING EDGE"
            if first_number(latest_cycle, ["crypto_qualified"], 0) > 0:
                state_name = "ACTIVE — QUALIFIED / ENTRY BLOCKED"
            if broker_positions:
                state_name = "ACTIVE — POSITION OPEN"
            elif working_orders:
                state_name = "ACTIVE — ORDER WORKING"
            exposure_state = state_name if engine_active else exposure_state
            activity_reason = (f"Scanned {int(first_number(latest_cycle, ['crypto_scanned'], 0))} · "
                               f"Qualified {int(first_number(latest_cycle, ['crypto_qualified'], 0))} · "
                               f"Lifecycle Blocked {int(first_number(latest_cycle, ['crypto_manifest_blocked'], 0))}")
        elif name == "International":
            exposure_state = ("ACTIVE — WAITING FOR SESSION" if engine_active and not broker_positions and not working_orders else exposure_state)
            activity_reason = (f"Instruments {int(first_number(latest_cycle, ['instruments_discovered'], 0))} · "
                               f"Venues {int(first_number(latest_cycle, ['venues_discovered'], 0))} · "
                               f"Open Venues {int(first_number(latest_cycle, ['venues_open'], 0))}")
        else:
            activity_reason = ""
        if legacy_call and not engine_active:
            exposure_state = "UNAVAILABLE"
        rows.append(
            {
                "name": name,
                "display": DISPLAY_NAMES.get(name, name),
                "engine_active": engine_active,
                "provider_available": engine_active,
                "state": exposure_state,
                "equity": equity,
                "deployed": deployed,
                "pending": pending,
                "available": available,
                "today_pnl": today_pnl,
                "daily_return": daily_return,
                "realized": realized,
                "unrealized": unrealized,
                "total_pnl": total_pnl,
                "positions": broker_positions,
                "working_orders": working_orders,
                "completed_today": completed_today,
                "activity_reason": activity_reason,
                "freshness": (
                    state.get("freshness", "MISSING")
                    if name != "Kalshi"
                    else ("FRESH" if str(kalshi.get("data", "")).upper() == "FRESH" else str(kalshi.get("data") or "MISSING"))
                ),
                "accounting_status": (foundation_pillars.get(
                    "Crypto" if name == "Crypto" else ("Stocks" if name == "stocks" else name), {}
                ).get("accounting_status", "ACCOUNTING_UNVERIFIED")
                    if isinstance(foundation_pillars.get("Crypto" if name == "Crypto" else name, {}), dict)
                    else "ACCOUNTING_UNVERIFIED"),
            }
                )
    return rows


def write_authoritative_portfolio_snapshot(pillars, *, output="var/reports/current-six-pillar-snapshot.json", observed_at=None):
    """Persist one read-time snapshot; values are never backfilled with zero."""
    observed_at = observed_at or datetime.now(UTC).isoformat()
    provider_meta = {
        "stocks": ("Alpaca", "PAPER"), "Crypto": ("Alpaca", "PAPER"),
        "Forex": ("OANDA", "PRACTICE"), "Metals / Commodities": ("Alpaca", "PAPER"),
        "International": ("Saxo", "SIM"), "Kalshi": ("Kalshi", "DEMO"),
    }
    rows = []
    for row in pillars:
        provider, environment = provider_meta.get(row.get("name"), (None, None))
        provider_equity = row.get("equity")
        economic_equity = provider_equity
        account_scope = "pillar"
        if provider == "Alpaca" and provider_equity is not None:
            # Alpaca Stocks/Crypto/Metals share one account.  Preserve the
            # broker balance as provenance, but expose only the logical
            # pillar allocation in each economic row.
            account_scope = "shared Alpaca PAPER account"
            economic_equity = BASE_CAPITAL + f(row.get("realized")) + f(row.get("unrealized"))
        field_sources = {}
        for field, value in {
            "equity": economic_equity, "deployed": row.get("deployed"),
            "pending": row.get("pending"), "available": row.get("available"),
            "realized": row.get("realized"), "unrealized": row.get("unrealized"),
        }.items():
            field_sources[field] = {
                "value": value, "source": "direct provider/runtime reads",
                "provider": provider, "account_scope": account_scope,
                "observed_at": observed_at,
                "freshness": row.get("freshness"),
            }
        rows.append({
            "pillar": row.get("name"), "provider": provider, "environment": environment,
            "account_scope": account_scope, "equity": economic_equity,
            "provider_account_equity": provider_equity,
            "economic_equity": economic_equity, "deployed": row.get("deployed"),
            "pending": row.get("pending"), "available": row.get("available"),
            "positions": row.get("positions"), "working_orders": row.get("working_orders"),
            "realized": row.get("realized"), "unrealized": row.get("unrealized"),
            "freshness": row.get("freshness"), "status": row.get("state"),
            "provenance": field_sources,
        })
    def total(field):
        values = [row[field] for row in rows]
        return None if any(value is None for value in values) else sum(float(value) for value in values)
    def equity_total():
        if any(row["equity"] is None for row in rows):
            return None
        return sum(float(row["equity"]) for row in rows)
    payload = {
        "observed_at": observed_at, "source": "direct provider/runtime reads",
        "live_trading_enabled": False, "real_money_orders": 0, "pillars": rows,
        "totals": {field: total(field) for field in ("deployed", "pending", "available", "realized", "unrealized")},
    }
    payload["totals"]["equity"] = equity_total()
    payload["totals"]["provider_account_equity"] = sum(
        float(row["provider_account_equity"])
        for row in rows
        if row.get("provider_account_equity") is not None
        and row.get("account_scope") != "shared Alpaca PAPER account"
    ) + sum(
        float(row["provider_account_equity"])
        for row in rows
        if row.get("provider_account_equity") is not None
        and row.get("account_scope") == "shared Alpaca PAPER account"
    ) / max(1, sum(row.get("account_scope") == "shared Alpaca PAPER account" for row in rows))
    payload["totals"]["provenance"] = {
        "economic_equity": {"value": payload["totals"]["equity"], "source": "logical pillar allocations and P&L", "observed_at": observed_at},
        "provider_account_equity": {"value": payload["totals"]["provider_account_equity"], "source": "provider account equity, deduplicated by account scope", "observed_at": observed_at},
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_international_position_reconciliation(provider_rows, owned_order_ids, *, output="var/reports/international-position-reconciliation.json", observed_at=None, error=None):
    """Persist Saxo exposure with ownership evidence; never adopt unknown lots."""
    observed_at = observed_at or datetime.now(UTC).isoformat()
    owned_order_ids = {str(value) for value in (owned_order_ids or set())}
    positions = []
    for row in provider_rows if isinstance(provider_rows, list) else []:
        base = row.get("PositionBase") if isinstance(row.get("PositionBase"), dict) else row
        view = row.get("PositionView") if isinstance(row.get("PositionView"), dict) else {}
        display = row.get("DisplayAndFormat") if isinstance(row.get("DisplayAndFormat"), dict) else {}
        source_order_id = str(base.get("SourceOrderId") or base.get("OrderId") or row.get("OrderId") or "")
        positions.append({
            "provider_position_id": row.get("PositionId") or row.get("NetPositionId"),
            "net_position_id": row.get("NetPositionId"), "uic": base.get("Uic"),
            "symbol": display.get("Symbol") or base.get("Symbol") or str(base.get("Uic") or ""),
            "description": display.get("Description"), "asset_type": base.get("AssetType"),
            "exchange": display.get("ExchangeId") or display.get("Exchange"),
            "direction": "LONG" if float(base.get("Amount") or 0) > 0 else "SHORT",
            "quantity": base.get("Amount"), "entry_open_price": base.get("OpenPrice"),
            "current_price": view.get("CurrentPrice"), "market_value": view.get("MarketValue"),
            "exposure": view.get("Exposure"), "unrealized_pnl": view.get("ProfitLossOnTrade"),
            "open_timestamp": base.get("ExecutionTimeOpen"), "source_order_id": source_order_id,
            "ownership": "PLATFORM_OWNED" if source_order_id in owned_order_ids else "EXTERNAL_OR_LEGACY_OR_UNKNOWN",
            "ownership_evidence": "current-epoch executed order match" if source_order_id in owned_order_ids else "not current-epoch platform ownership",
        })
    payload = {
        "observed_at": observed_at, "provider": "Saxo", "environment": "SIM",
        "position_count": len(positions),
        "platform_owned_positions": sum(p["ownership"] == "PLATFORM_OWNED" for p in positions),
        "broker_exposed_positions": len(positions),
        "external_legacy_unknown_positions": sum(p["ownership"] != "PLATFORM_OWNED" for p in positions),
        "positions": positions, "error": error,
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_international_execution_funnel(current, *, output="var/reports/international-execution-funnel.json", observed_at=None):
    """Publish the latest bounded runtime funnel without inventing activity."""
    payload = dict(current) if isinstance(current, dict) else {}
    payload["last_observed_at"] = observed_at or datetime.now(UTC).isoformat()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _load_high_velocity():
    path = Path("var/autotrader/learning/high-velocity-research.json")
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_lane_summary():
    path = Path("var/autotrader/learning/paper-lane-summary.json")
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_foundation_report():
    path = Path("var/autotrader/foundation-report.json")
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def main():
    st.markdown('<meta http-equiv="refresh" content="20">', unsafe_allow_html=True)
    st.set_page_config(page_title="Trading Performance", layout="wide")
    st.markdown(
        """
        <style>
        .block-container{max-width:1100px;padding-top:1rem;padding-bottom:2rem}
        [data-testid="stHeader"],[data-testid="stSidebar"]{display:none}
        .title{font-size:2rem;font-weight:800;margin-bottom:.1rem}
        .sub{color:#8b98aa;margin-bottom:1rem}
        .ok{color:#36c98f;font-weight:700}
        .muted{color:#8b98aa;font-size:.85rem}
        </style>
        """,
        unsafe_allow_html=True,
    )

    snapshot = core.load_snapshot()
    runtime = core.load_live_runtime_status()
    if not isinstance(runtime, dict) or not runtime:
        runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}

    try:
        live_positions, _, live_status, _ = core.fetch_live_broker_data()
    except Exception:
        live_positions, live_status = [], {}

    try:
        kalshi = core._kalshi_status()
    except Exception:
        kalshi = {}

    try:
        saxo_live = _saxo_live_truth()
    except Exception:
        saxo_live = {}

    try:
        crypto_history = core._alpaca_crypto_history()
        crypto_realized_today = crypto_history.get("realized_today")
    except Exception:
        crypto_realized_today = None

    pillars = build_pillars(
        snapshot,
        runtime,
        live_status,
        kalshi,
        live_positions,
        saxo_live,
        crypto_realized_today=crypto_realized_today,
        foundation_report=_load_foundation_report(),
    )

    def total(field):
        vals = [row.get(field) for row in pillars if row.get(field) is not None]
        return sum(vals) if vals else 0.0

    deployed = total("deployed")
    pending = total("pending")
    available = max(FUND_STARTING_CAPITAL - deployed - pending, 0.0)
    today_pnl = total("today_pnl")
    realized_today = total("realized")
    unrealized = total("unrealized")
    def strategy_visible(row):
        if row.get("name") == "Kalshi":
            return False
        status = str(row.get("accounting_status") or "").upper()
        return status in {"ACCOUNTING_VERIFIED", ""} or bool(row.get("engine_active"))

    open_positions = sum(int(row.get("positions") or 0) for row in pillars if strategy_visible(row))
    working_orders = sum(int(row.get("working_orders") or 0) for row in pillars if strategy_visible(row))
    trades_today = sum(int(row.get("completed_today") or 0) for row in pillars if strategy_visible(row))

    cash = snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {}
    week_pnl = first_number(cash, ["verified_net_pnl_week", "weekly_realized_pnl", "week_pnl"], 0.0)

    learning = snapshot.get("learning") if isinstance(snapshot.get("learning"), dict) else {}
    wins = int(first_number(learning, ["wins_today", "wins"], 0.0))
    losses = int(first_number(learning, ["losses_today", "losses"], 0.0))
    closed = wins + losses
    win_rate = (wins / closed * 100.0) if closed else 0.0

    velocity = snapshot.get("cash_velocity") if isinstance(snapshot.get("cash_velocity"), dict) else {}
    cash_per_hour = first_number(
        velocity,
        ["verified_cash_per_hour", "cash_per_hour"],
        first_number(cash, ["cash_per_hour", "verified_cash_per_hour"], 0.0),
    )

    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    execution_state = str(runtime.get("execution_state") or runtime.get("state") or "").lower()
    heartbeat_seen = any(
        isinstance(job, dict) and (job.get("last_started_at") or job.get("last_finished_at"))
        for job in jobs.values()
    )
    active = (
        execution_state in {"armed_paper", "active", "running"}
        or bool(runtime.get("healthy"))
        or heartbeat_seen
    ) and not bool(runtime.get("fatal_error"))
    last_refresh = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    ranked = sorted(
        pillars,
        key=lambda row: (f(row.get("today_pnl")), f(row.get("realized"))),
        reverse=True,
    )
    best = ranked[0]["display"] if ranked else "Collecting data"

    st.markdown('<div class="title">Trading Performance</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sub"><span class="ok">● {"ACTIVE" if active else "CHECK ENGINE"}</span> · '
        f'Paper/PRACTICE only · refreshed {last_refresh}</div>',
        unsafe_allow_html=True,
    )

    a = st.columns(4)
    a[0].metric("Authorized", money(FUND_STARTING_CAPITAL))
    a[1].metric("Deployed", money(deployed))
    a[2].metric("Available", money(available))
    a[3].metric("Deployment", f"{(deployed / FUND_STARTING_CAPITAL * 100):.1f}%")

    b = st.columns(4)
    b[0].metric("Today P&L", signed_money(today_pnl))
    b[1].metric("Week P&L", signed_money(week_pnl))
    b[2].metric("Realized Today", signed_money(realized_today))
    b[3].metric("Unrealized", signed_money(unrealized))

    c = st.columns(4)
    c[0].metric("Open Positions", str(open_positions))
    c[1].metric("Working Orders", str(working_orders))
    c[2].metric("Trades Today", str(trades_today))
    c[3].metric("Win Rate", f"{win_rate:.1f}% ({wins}W/{losses}L)")

    d = st.columns(2)
    d[0].metric("Cash / Hour", signed_money(cash_per_hour))
    d[1].metric("Best Pillar", best)

    st.markdown("### Pillars")
    for row in pillars:
        visible = strategy_visible(row)
        shown_positions = int(row.get("positions") or 0) if visible else 0
        shown_deployed = row.get("deployed") if visible else 0.0
        shown_pnl = row.get("today_pnl") if visible else 0.0
        cols = st.columns([2.2, 1.3, 1.3, 1.0])
        cols[0].markdown(f"**{row['display']}**")
        cols[1].metric("Deployed", money(shown_deployed))
        cols[2].metric("Today", signed_money(shown_pnl))
        cols[3].metric("Positions", str(shown_positions))

    st.markdown(
        '<div class="muted">Verified strategy performance only · legacy/unverified provider inventory excluded · read-only.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
