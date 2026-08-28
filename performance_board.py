from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

import streamlit_app as core

# Read-only observation board. No controls in this module may alter trading,
# allocation, execution, strategy, risk, credentials, or provider state.
# This board intentionally has no auto-refresh loop. Data reloads only when
# the user manually refreshes/reloads the Streamlit page.

PILLAR_ORDER = [
    "US Stocks / ETFs",
    "Crypto",
    "Forex",
    "Metals / Commodities",
    "International",
    "Kalshi",
]
DISPLAY_NAMES = {
    "US Stocks / ETFs": "Stocks",
    "Metals / Commodities": "Metals / Commodities",
}
PILLAR_JOB_MAP = {
    "US Stocks / ETFs": "autonomous-paper-trading",
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


def _live_position_totals(live_positions):
    totals = {name: {"deployed": 0.0, "market_value": 0.0, "unrealized": 0.0, "positions": 0} for name in PILLAR_ORDER}
    for row in live_positions if isinstance(live_positions, list) else []:
        if not isinstance(row, dict):
            continue
        pillar = str(row.get("pillar") or "")
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
        payload = adapter.list_positions(account_key=account_key)
        rows = payload.get("Data", []) if isinstance(payload, dict) else []
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
            result["deployed"] += cost_basis
            result["market_value"] += exposure if exposure else max(cost_basis + pnl, 0.0)
            result["unrealized"] += pnl
            result["positions"] += 1
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


def build_pillars(snapshot, runtime, live_status=None, kalshi=None, live_positions=None, saxo_live=None):
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
    perf = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    latest_cycle = snapshot.get("latest_cycle") if isinstance(snapshot.get("latest_cycle"), dict) else {}
    broker_totals = _live_position_totals(live_positions)
    rows = []
    for name in PILLAR_ORDER:
        p = perf.get(name) if isinstance(perf.get(name), dict) else {}
        state = live_status.get(name) if isinstance(live_status.get(name), dict) else {}
        broker = broker_totals.get(name, {})
        broker_positions = int(f(broker.get("positions")))
        working_orders = int(f(state.get("working_orders")))

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

        completed_today = int(first_number(p, ["completed_trades_today", "completed_today", "completed_trades"], 0.0))
        today_pnl = first_number(p, ["today_pnl", "daily_pnl", "total_today", "realized_today"], realized + unrealized)
        total_pnl = first_number(p, ["total_pnl", "net_pnl", "net_generated_cash"], realized) + unrealized
        available = max(BASE_CAPITAL - deployed - pending, 0.0)
        equity = BASE_CAPITAL + total_pnl
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
            }
        )
    return rows


def _load_high_velocity():
    path = Path("var/autotrader/learning/high-velocity-research.json")
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def main():
    st.markdown(
        """
        <style>
        :root{--bg:#06111e;--panel:#101827;--line:#26364d;--text:#f4f7fb;--muted:#91a1b8;--green:#57d79b;--red:#ff7f8b;--gold:#d8b66c;--blue:#69b7ff;}
        .stApp{background:linear-gradient(180deg,#071522 0%,#050b13 100%);color:var(--text)}
        .block-container{max-width:1200px;padding-top:.7rem;padding-bottom:3rem}
        [data-testid="stHeader"],[data-testid="stSidebar"]{display:none}
        .board-title{font-size:clamp(1.6rem,4vw,2.7rem);font-weight:850;letter-spacing:-.03em;margin:.2rem 0}
        .board-sub{color:var(--muted);font-size:.88rem;margin-bottom:.45rem}
        .live{font-size:.72rem;color:var(--green);margin:.2rem 0 .8rem;font-weight:700}
        .section{font-size:.76rem;letter-spacing:.17em;text-transform:uppercase;color:var(--gold);font-weight:800;margin:1.25rem 0 .6rem}
        [data-testid="stMetric"]{background:linear-gradient(180deg,#111a2a,#0d1522);border:1px solid var(--line);border-radius:15px;padding:.5rem .68rem}
        [data-testid="stMetricLabel"]{color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.07em}
        [data-testid="stMetricValue"]{font-size:1.24rem;font-weight:800;color:var(--text)}
        .fund-status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.55rem;margin:.5rem 0 .9rem}
        .fund-status>div{background:#0c1623;border:1px solid var(--line);border-radius:14px;padding:.7rem}
        .fund-status .k{color:var(--muted);font-size:.62rem;text-transform:uppercase;letter-spacing:.08em}
        .fund-status .v{font-size:1rem;font-weight:850;margin-top:.18rem}
        .pillar-card{background:linear-gradient(180deg,#111a2a,#0c1420);border:1px solid var(--line);border-radius:18px;padding:.9rem;margin:.3rem 0 .62rem}
        .pillar-head{display:flex;justify-content:space-between;gap:.7rem;align-items:flex-start;margin-bottom:.35rem}
        .pillar-name{font-size:1.12rem;font-weight:850}.engine{font-size:.68rem;color:var(--green);font-weight:850;letter-spacing:.07em}.engine-off{color:var(--red)}
        .market-state{font-size:.77rem;color:var(--blue);font-weight:750;margin-bottom:.72rem}
        .pillar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem}
        .k{color:var(--muted);font-size:.62rem;text-transform:uppercase;letter-spacing:.07em}.v{font-size:.98rem;font-weight:800;margin-top:.1rem}
        .pos{color:var(--green)}.neg{color:var(--red)}.neutral{color:var(--text)}
        .goal{border:1px solid rgba(216,182,108,.45);background:rgba(216,182,108,.06);border-radius:15px;padding:.75rem .9rem;margin-top:.8rem}
        .goal-top{display:flex;justify-content:space-between;gap:.8rem;align-items:center}.goal strong{font-size:1rem}.goal small{color:var(--muted)}
        .bar{height:7px;background:#172235;border-radius:999px;overflow:hidden;margin-top:.5rem}.bar>div{height:100%;background:linear-gradient(90deg,#d8b66c,#57d79b)}
        @media(max-width:760px){.block-container{padding-left:.65rem;padding-right:.65rem}.pillar-grid,.fund-status{grid-template-columns:repeat(2,minmax(0,1fr))}.board-title{font-size:1.55rem}[data-testid="stMetricValue"]{font-size:1.05rem}.pillar-card{padding:.78rem}.pillar-name{font-size:1.02rem}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    snapshot = core.load_snapshot()
    runtime = core.load_live_runtime_status()
    if not isinstance(runtime, dict) or not runtime:
        runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    core.fetch_live_broker_data.clear()
    live_positions, _, live_status, live_errors = core.fetch_live_broker_data()
    kalshi = core._kalshi_status()
    saxo_live = _saxo_live_truth()
    pillars = build_pillars(snapshot, runtime, live_status, kalshi, live_positions, saxo_live)

    fund_equity = sum(row["equity"] for row in pillars)
    deployed = sum(row["deployed"] for row in pillars)
    pending = sum(row["pending"] for row in pillars)
    available = sum(row["available"] for row in pillars)
    realized_today = sum(row["realized"] for row in pillars)
    unrealized = sum(row["unrealized"] for row in pillars)
    today_pnl = sum(row["today_pnl"] for row in pillars)
    total_pnl = fund_equity - FUND_STARTING_CAPITAL
    daily_return = today_pnl / FUND_STARTING_CAPITAL if FUND_STARTING_CAPITAL else 0.0
    active_count = sum(1 for row in pillars if row["engine_active"])
    deployed_count = sum(1 for row in pillars if row["deployed"] > 0 or row["pending"] > 0)
    position_count = sum(int(row["positions"]) for row in pillars)
    order_count = sum(int(row["working_orders"]) for row in pillars)

    st.markdown('<div class="board-title">AUTONOMOUS FUND PERFORMANCE</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="board-sub">Read-only six-pillar performance board · engine activity separated from capital exposure</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="live">● LIVE PROVIDER SNAPSHOT · {datetime.now(UTC).strftime("%H:%M:%S UTC")} · MANUAL REFRESH ONLY</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""<div class="fund-status">
        <div><div class="k">Execution Engines</div><div class="v {"pos" if active_count == 6 else "neg"}">{active_count}/6 ACTIVE</div></div>
        <div><div class="k">Pillars With Capital</div><div class="v">{deployed_count}/6 DEPLOYED / PENDING</div></div>
        <div><div class="k">Positions / Orders</div><div class="v">{position_count} / {order_count}</div></div>
        </div>""",
        unsafe_allow_html=True,
    )

    if live_errors:
        st.warning("Provider read warning: " + " · ".join(live_errors))
    if saxo_live.get("error"):
        st.warning("International provider read warning: " + str(saxo_live.get("error")))

    a = st.columns(4)
    a[0].metric("Current Equity", money(fund_equity))
    a[1].metric("Capital Deployed", money(deployed))
    a[2].metric("Available Cash", money(available))
    a[3].metric("Pending Capital", money(pending))
    b = st.columns(4)
    b[0].metric("Today P&L", signed_money(today_pnl))
    b[1].metric("Daily Return", signed_pct(daily_return))
    b[2].metric("Realized Today", signed_money(realized_today))
    b[3].metric("Unrealized P&L", signed_money(unrealized))
    c = st.columns(2)
    c[0].metric("Total P&L", signed_money(total_pnl))
    c[1].metric("Total Return", signed_pct(total_pnl / FUND_STARTING_CAPITAL))

    cash_progress = min(max(realized_today / DAILY_CASH_STRETCH, 0.0), 1.0)
    st.markdown(
        f'<div class="goal"><div class="goal-top"><div><small>DAILY REALIZED CASH</small><br><strong>{signed_money(realized_today)}</strong></div><div><small>FLOOR / STRETCH</small><br><strong>$500 / $1,000</strong></div></div><div class="bar"><div style="width:{cash_progress * 100:.1f}%"></div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section">Six Pillar Performance</div>', unsafe_allow_html=True)
    for row in pillars:
        pnl_class = "pos" if row["today_pnl"] > 0 else "neg" if row["today_pnl"] < 0 else "neutral"
        total_class = "pos" if row["total_pnl"] > 0 else "neg" if row["total_pnl"] < 0 else "neutral"
        engine_class = "engine" if row["engine_active"] else "engine engine-off"
        engine_label = "ENGINE ACTIVE" if row["engine_active"] else "ENGINE DEGRADED"
        st.markdown(
            f"""<div class="pillar-card">
            <div class="pillar-head"><div class="pillar-name">{row["display"]}</div><div class="{engine_class}">{engine_label}</div></div>
            <div class="market-state">{row["state"]}</div>
            <div class="board-sub">{row["activity_reason"]}</div>
            <div class="pillar-grid">
              <div><div class="k">Equity</div><div class="v">{money(row["equity"])}</div></div>
              <div><div class="k">Deployed</div><div class="v">{money(row["deployed"])}</div></div>
              <div><div class="k">Available</div><div class="v">{money(row["available"])}</div></div>
              <div><div class="k">Today P&L</div><div class="v {pnl_class}">{signed_money(row["today_pnl"])}</div></div>
              <div><div class="k">Daily Return</div><div class="v {pnl_class}">{signed_pct(row["daily_return"])}</div></div>
              <div><div class="k">Total P&L</div><div class="v {total_class}">{signed_money(row["total_pnl"])}</div></div>
              <div><div class="k">Realized Today</div><div class="v">{signed_money(row["realized"])}</div></div>
              <div><div class="k">Unrealized</div><div class="v">{signed_money(row["unrealized"])}</div></div>
              <div><div class="k">Positions / Orders</div><div class="v">{row["positions"]} / {row["working_orders"]}</div></div>
              <div><div class="k">Trades Today</div><div class="v">{row["completed_today"]}</div></div>
            </div></div>""",
            unsafe_allow_html=True,
        )

    hv = _load_high_velocity()
    micro_candidates = len(hv.get("micro_candidates", [])) if isinstance(hv.get("micro_candidates"), list) else 0
    derivatives = len(hv.get("derivatives", [])) if isinstance(hv.get("derivatives"), list) else 0
    arbitrage = len(hv.get("arbitrage", [])) if isinstance(hv.get("arbitrage"), list) else 0
    st.markdown('<div class="section">Learning & High-Velocity Research</div>', unsafe_allow_html=True)
    h = st.columns(4)
    h[0].metric("Learning", "ACTIVE" if _runtime_job_active(runtime, "daily-learning") else "COLLECTING")
    h[1].metric("Micro Candidates", str(micro_candidates))
    h[2].metric("Derivative Sims", str(derivatives))
    h[3].metric("Arbitrage Sims", str(arbitrage))
    if hv.get("updated_at"):
        st.caption(f"High-velocity research last update: {hv.get('updated_at')}")

    # Realized cash is the primary research objective. Simulated lanes remain
    # explicitly separate from provider-realized cash and never affect equity.
    st.markdown('<div class="section">Cash Generation & Research</div>', unsafe_allow_html=True)
    realized_today = sum(float(row.get("realized") or 0.0) for row in pillars)
    lane_rows = hv.get("lanes") if isinstance(hv.get("lanes"), dict) else {}
    def lane_pnl(name):
        row = lane_rows.get(name, {}) if isinstance(lane_rows, dict) else {}
        return signed_money(row.get("realized_pnl", row.get("simulated_pnl", 0.0))) if isinstance(row, dict) else signed_money(0.0)
    st.markdown(
        f'''<div class="fund-status">
        <div><div class="k">Realized Today</div><div class="v">{signed_money(realized_today)}</div></div>
        <div><div class="k">$500 Goal Progress</div><div class="v">{realized_today / DAILY_CASH_FLOOR * 100:.1f}%</div></div>
        <div><div class="k">$1,000 Goal Progress</div><div class="v">{realized_today / DAILY_CASH_STRETCH * 100:.1f}%</div></div>
        <div><div class="k">Best Cash Generator</div><div class="v">REALIZED NET P&L</div></div>
        <div><div class="k">Best Capital Efficiency</div><div class="v">EVIDENCE COLLECTING</div></div>
        <div><div class="k">Day / Short / Derivative / Arbitrage</div><div class="v">{lane_pnl("DAY_TRADE")} / {lane_pnl("SHORT")} / {lane_pnl("DERIVATIVE_SIM")} / {lane_pnl("ARBITRAGE_SIM")}</div></div>
        </div>''', unsafe_allow_html=True,
    )

    st.markdown('<div class="section">Annual Income Objective</div>', unsafe_allow_html=True)
    cash = snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {}
    yearly_realized = first_number(cash, ["net_trading_cash_generated", "cumulative_realized_pnl"], 0.0)
    d = st.columns(4)
    d[0].metric("Annual Goal", money(ANNUAL_GOAL))
    d[1].metric("Realized YTD", money(yearly_realized))
    d[2].metric("Remaining", money(max(ANNUAL_GOAL - yearly_realized, 0.0)))
    d[3].metric("Goal Progress", signed_pct(yearly_realized / ANNUAL_GOAL if ANNUAL_GOAL else 0.0))

    st.caption(
        "ENGINE ACTIVE means the provider/runtime execution loop is running. ACTIVE — POSITION OPEN means capital is currently deployed. ACTIVE — SEEKING EDGE means the engine is live and evaluating but is currently flat."
    )


if __name__ == "__main__":
    main()
