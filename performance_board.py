from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

import streamlit_app as core

# streamlit_app owns page configuration. This module intentionally contains
# no controls that can modify trading, risk, allocation, or execution state.

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


def pct(value):
    return f"{f(value) * 100:.2f}%"


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


def row_money(row, key, signed=False):
    if not row.get("provider_available"):
        return "UNAVAILABLE"
    return signed_money(row.get(key)) if signed else money(row.get(key))


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


def provider_state(name, broker_state, kalshi, broker_positions=0, working_orders=0):
    if name == "Kalshi":
        conn = str(kalshi.get("connection") or "")
        if conn.startswith("CONNECTED"):
            if broker_positions > 0:
                return "ACTIVE"
            if working_orders > 0:
                return "ORDER WORKING"
            return "OPERATIONAL"
        return conn or "UNAVAILABLE"
    if broker_state.get("connected"):
        if broker_positions > 0 or f(broker_state.get("positions")) > 0:
            return "ACTIVE"
        if working_orders > 0 or f(broker_state.get("working_orders")) > 0:
            return "ORDER WORKING"
        return "OPERATIONAL"
    return "UNAVAILABLE"


def _live_position_totals(live_positions):
    totals = {name: {"deployed": 0.0, "market_value": 0.0, "unrealized": 0.0, "positions": 0} for name in PILLAR_ORDER}
    for row in live_positions if isinstance(live_positions, list) else []:
        if not isinstance(row, dict):
            continue
        pillar = str(row.get("pillar") or "")
        if pillar not in totals:
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
    """Read current Saxo SIM positions directly for display-only broker truth."""
    result = {
        "connected": False,
        "deployed": 0.0,
        "market_value": 0.0,
        "unrealized": 0.0,
        "positions": 0,
        "working_orders": 0,
        "trade_level": "",
        "completed_today": 0,
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


def build_pillars(snapshot, live_status, kalshi, live_positions, saxo_live):
    perf = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
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
            realized = first_number(kalshi, ["v2_realized_pnl", "perps_realized_pnl", "realized_pnl"], first_number(p, ["net_generated_cash", "realized_pnl"], 0.0))
            broker_positions = int(first_number(kalshi, ["perps_positions", "predictions_positions", "positions"], 0.0))
            working_orders = int(first_number(kalshi, ["perps_open_orders", "predictions_open_orders", "open_orders"], 0.0))
        elif name == "International" and saxo_live.get("connected"):
            deployed = f(saxo_live.get("deployed"))
            pending = 0.0
            unrealized = f(saxo_live.get("unrealized"))
            realized = first_number(p, ["realized_today", "daily_realized_pnl", "net_generated_cash", "realized_pnl"], 0.0)
            broker_positions = int(f(saxo_live.get("positions")))
            working_orders = int(f(saxo_live.get("working_orders")))
        else:
            # Display broker-confirmed positions first. Strategy accounting is a
            # fallback only; the observation board must never hide an open
            # position because a manifest/classification record is stale.
            broker_deployed = f(broker.get("deployed"))
            deployed = broker_deployed if broker_positions > 0 else first_number(state, ["strategy_cost_basis", "strategy_deployed"], 0.0)
            pending = first_number(state, ["pending_capital"], 0.0)
            broker_unrealized = f(broker.get("unrealized"))
            unrealized = broker_unrealized if broker_positions > 0 else first_number(state, ["unrealized_pnl"], first_number(p, ["unrealized_pnl"], 0.0))
            realized = first_number(p, ["realized_today", "daily_realized_pnl", "net_generated_cash", "realized_pnl"], 0.0)

        completed_today = int(first_number(p, ["completed_trades_today", "completed_today", "completed_trades"], 0.0))
        if name == "International":
            completed_today = int(first_number(saxo_live, ["completed_today"], completed_today))

        today_pnl = first_number(p, ["today_pnl", "daily_pnl", "total_today", "realized_today"], realized + unrealized)
        total_pnl = first_number(p, ["total_pnl", "net_pnl", "net_generated_cash"], realized) + unrealized
        available = max(BASE_CAPITAL - deployed - pending, 0.0)
        equity = BASE_CAPITAL + total_pnl
        daily_return = today_pnl / BASE_CAPITAL if BASE_CAPITAL else 0.0
        rows.append({
            "name": name,
            "display": DISPLAY_NAMES.get(name, name),
            "state": provider_state(name, state, kalshi, broker_positions, working_orders),
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
            "provider_available": bool(
                (name == "Kalshi" and str(kalshi.get("connection") or "").startswith("CONNECTED"))
                or (name != "Kalshi" and state.get("connected"))
                or (name == "International" and saxo_live.get("connected"))
            ),
            "legacy_exposure": f(state.get("legacy_exposure")),
            "allocation": BASE_CAPITAL,
            "allocation_breach": name == "US Stocks / ETFs" and deployed > BASE_CAPITAL,
        })
    return rows


def main():
    st.markdown(
        """
        <style>
        :root{--bg:#06111e;--panel:#101827;--line:#26364d;--text:#f4f7fb;--muted:#91a1b8;--green:#57d79b;--red:#ff7f8b;--gold:#d8b66c;}
        .stApp{background:linear-gradient(180deg,#071522 0%,#050b13 100%);color:var(--text)}
        .block-container{max-width:1200px;padding-top:1rem;padding-bottom:3rem}
        [data-testid="stHeader"],[data-testid="stSidebar"]{display:none}
        .board-title{font-size:clamp(1.7rem,4vw,3rem);font-weight:800;letter-spacing:-.03em;margin:.2rem 0}
        .board-sub{color:var(--muted);font-size:.9rem;margin-bottom:1rem}
        .section{font-size:.78rem;letter-spacing:.18em;text-transform:uppercase;color:var(--gold);font-weight:800;margin:1.4rem 0 .65rem}
        [data-testid="stMetric"]{background:linear-gradient(180deg,#111a2a,#0d1522);border:1px solid var(--line);border-radius:16px;padding:.55rem .75rem}
        [data-testid="stMetricLabel"]{color:var(--muted);font-size:.69rem;text-transform:uppercase;letter-spacing:.08em}
        [data-testid="stMetricValue"]{font-size:1.32rem;font-weight:800;color:var(--text)}
        .pillar-card{background:linear-gradient(180deg,#111a2a,#0c1420);border:1px solid var(--line);border-radius:18px;padding:1rem;margin:.35rem 0 .65rem}
        .pillar-head{display:flex;justify-content:space-between;gap:1rem;align-items:center;margin-bottom:.85rem}
        .pillar-name{font-size:1.1rem;font-weight:800}.pillar-state{font-size:.72rem;color:var(--green);font-weight:800;letter-spacing:.08em}
        .pillar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.8rem}
        .k{color:var(--muted);font-size:.65rem;text-transform:uppercase;letter-spacing:.08em}.v{font-size:1rem;font-weight:800;margin-top:.12rem}
        .pos{color:var(--green)}.neg{color:var(--red)}.neutral{color:var(--text)}
        .goal{border:1px solid rgba(216,182,108,.45);background:rgba(216,182,108,.06);border-radius:16px;padding:.8rem 1rem;margin-top:.9rem}
        .goal-top{display:flex;justify-content:space-between;gap:1rem;align-items:center}.goal strong{font-size:1.05rem}.goal small{color:var(--muted)}
        .bar{height:8px;background:#172235;border-radius:999px;overflow:hidden;margin-top:.55rem}.bar>div{height:100%;background:linear-gradient(90deg,#d8b66c,#57d79b)}
        .live{font-size:.72rem;color:var(--green);margin:.3rem 0 1rem}
        @media(max-width:760px){.block-container{padding-left:.75rem;padding-right:.75rem}.pillar-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.board-title{font-size:1.65rem}[data-testid="stMetricValue"]{font-size:1.12rem}.pillar-card{padding:.85rem}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    snapshot = core.load_snapshot()
    core.fetch_live_broker_data.clear()
    live_positions, _, live_status, live_errors = core.fetch_live_broker_data()
    kalshi = core._kalshi_status()
    saxo_live = _saxo_live_truth()
    pillars = build_pillars(snapshot, live_status, kalshi, live_positions, saxo_live)

    fund_equity = sum(row["equity"] for row in pillars)
    deployed = sum(row["deployed"] for row in pillars)
    pending = sum(row["pending"] for row in pillars)
    available = sum(row["available"] for row in pillars)
    today_pnl = sum(row["today_pnl"] for row in pillars)
    realized_today = sum(row["realized"] for row in pillars)
    unrealized = sum(row["unrealized"] for row in pillars)
    total_pnl = fund_equity - FUND_STARTING_CAPITAL
    daily_return = today_pnl / FUND_STARTING_CAPITAL if FUND_STARTING_CAPITAL else 0.0

    st.markdown('<div class="board-title">AUTONOMOUS FUND PERFORMANCE</div>', unsafe_allow_html=True)
    st.markdown('<div class="board-sub">Read-only live performance board · direct broker/provider position truth · no trading controls</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="live">● LIVE PROVIDER SNAPSHOT · Last loaded: {datetime.now(UTC).strftime("%H:%M:%S UTC")} · Reload page for current data</div>', unsafe_allow_html=True)
    provider_errors = list(live_errors)
    if saxo_live.get("error"):
        provider_errors.append("International: " + str(saxo_live.get("error")))
    if provider_errors:
        st.warning("Some provider reads are degraded: " + " · ".join(provider_errors))
    breaches = [
        f'{row["display"]}: deployed {money(row["deployed"])} exceeds {money(row["allocation"])} paper allocation'
        for row in pillars if row.get("allocation_breach")
    ]
    if breaches:
        st.error("Paper allocation/accounting defect: " + " · ".join(breaches) + ". Legacy/external exposure is reported separately in provider truth.")

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
        f'<div class="goal"><div class="goal-top"><div><small>DAILY REALIZED CASH</small><br><strong>{signed_money(realized_today)}</strong></div><div><small>FLOOR / STRETCH</small><br><strong>$500 / $1,000</strong></div></div><div class="bar"><div style="width:{cash_progress*100:.1f}%"></div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section">Six Pillar Performance</div>', unsafe_allow_html=True)
    for row in pillars:
        pnl_class = "pos" if row["today_pnl"] > 0 else "neg" if row["today_pnl"] < 0 else "neutral"
        total_class = "pos" if row["total_pnl"] > 0 else "neg" if row["total_pnl"] < 0 else "neutral"
        st.markdown(
            f'''<div class="pillar-card">
            <div class="pillar-head"><div class="pillar-name">{row["display"]}</div><div class="pillar-state">{row["state"]}</div></div>
            <div class="pillar-grid">
              <div><div class="k">Equity</div><div class="v">{row_money(row, "equity")}</div></div>
              <div><div class="k">Deployed</div><div class="v">{row_money(row, "deployed")}</div></div>
              <div><div class="k">Available</div><div class="v">{row_money(row, "available")}</div></div>
              <div><div class="k">Today P&L</div><div class="v {pnl_class}">{row_money(row, "today_pnl", True)}</div></div>
              <div><div class="k">Daily Return</div><div class="v {pnl_class}">{"UNAVAILABLE" if not row["provider_available"] else signed_pct(row["daily_return"])}</div></div>
              <div><div class="k">Total P&L</div><div class="v {total_class}">{row_money(row, "total_pnl", True)}</div></div>
              <div><div class="k">Realized</div><div class="v">{row_money(row, "realized", True)}</div></div>
              <div><div class="k">Unrealized</div><div class="v">{row_money(row, "unrealized", True)}</div></div>
              <div><div class="k">Positions / Orders</div><div class="v">{"UNAVAILABLE" if not row["provider_available"] else f'{row["positions"]} / {row["working_orders"]}'}</div></div>
              <div><div class="k">Completed Today</div><div class="v">{"UNAVAILABLE" if not row["provider_available"] else row["completed_today"]}</div></div>
            </div></div>''',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section">Annual Income Objective</div>', unsafe_allow_html=True)
    yearly_realized = first_number(snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {}, ["net_trading_cash_generated", "cumulative_realized_pnl"], 0.0)
    goal_progress = min(max(yearly_realized / ANNUAL_GOAL, 0.0), 1.0)
    d = st.columns(4)
    d[0].metric("Annual Goal", money(ANNUAL_GOAL))
    d[1].metric("Realized YTD", money(yearly_realized))
    d[2].metric("Remaining", money(max(ANNUAL_GOAL - yearly_realized, 0.0)))
    d[3].metric("Goal Progress", pct(goal_progress))

    st.caption("Observation board only. Strategy, risk, execution, research and learning continue in the existing autonomous services.")


if __name__ == "__main__":
    main()
