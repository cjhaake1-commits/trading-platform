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
    return f"${f(value):,.2f}"


def pct(value):
    return f"{f(value) * 100:.2f}%"


def signed_money(value):
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


def provider_state(name, broker_state, kalshi):
    if name == "Kalshi":
        conn = str(kalshi.get("connection") or "")
        if conn.startswith("CONNECTED"):
            return "OPERATIONAL"
        return conn or "UNAVAILABLE"
    if broker_state.get("connected"):
        if f(broker_state.get("positions")) > 0:
            return "ACTIVE"
        if f(broker_state.get("working_orders")) > 0:
            return "ORDER WORKING"
        return "OPERATIONAL"
    return "UNAVAILABLE"


def build_pillars(snapshot, live_status, kalshi):
    perf = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    rows = []
    for name in PILLAR_ORDER:
        p = perf.get(name) if isinstance(perf.get(name), dict) else {}
        state = live_status.get(name) if isinstance(live_status.get(name), dict) else {}
        if name == "Kalshi":
            deployed = first_number(kalshi, ["v2_deployed", "perps_deployed", "deployed"], 0.0)
            pending = first_number(kalshi, ["pending_capital", "pending"], 0.0)
            unrealized = first_number(kalshi, ["v2_unrealized_pnl", "perps_unrealized_pnl", "unrealized_pnl"], 0.0)
            realized = first_number(kalshi, ["v2_realized_pnl", "perps_realized_pnl", "realized_pnl"], first_number(p, ["net_generated_cash", "realized_pnl"], 0.0))
        else:
            deployed = first_number(state, ["strategy_cost_basis", "strategy_deployed"], 0.0)
            pending = first_number(state, ["pending_capital"], 0.0)
            unrealized = first_number(state, ["unrealized_pnl"], first_number(p, ["unrealized_pnl"], 0.0))
            realized = first_number(p, ["realized_today", "daily_realized_pnl", "net_generated_cash", "realized_pnl"], 0.0)
        today_pnl = first_number(p, ["today_pnl", "daily_pnl", "total_today", "realized_today"], realized + unrealized)
        total_pnl = first_number(p, ["total_pnl", "net_pnl", "net_generated_cash"], realized) + unrealized
        available = max(BASE_CAPITAL - deployed - pending, 0.0)
        equity = BASE_CAPITAL + total_pnl
        daily_return = today_pnl / BASE_CAPITAL if BASE_CAPITAL else 0.0
        rows.append({
            "name": name,
            "display": DISPLAY_NAMES.get(name, name),
            "state": provider_state(name, state, kalshi),
            "equity": equity,
            "deployed": deployed,
            "pending": pending,
            "available": available,
            "today_pnl": today_pnl,
            "daily_return": daily_return,
            "realized": realized,
            "unrealized": unrealized,
            "total_pnl": total_pnl,
            "positions": int(first_number(state, ["positions"], first_number(kalshi, ["perps_positions", "positions"], 0))),
        })
    return rows


def main():
    st.markdown("<meta http-equiv='refresh' content='20'>", unsafe_allow_html=True)
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
    _, _, live_status, live_errors = core.fetch_live_broker_data()
    kalshi = core._kalshi_status()
    pillars = build_pillars(snapshot, live_status, kalshi)

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
    st.markdown('<div class="board-sub">Read-only live performance board · six pillars · no trading controls</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="live">● LIVE · refreshed {datetime.now(UTC).strftime("%H:%M:%S UTC")} · auto-refresh 20s</div>', unsafe_allow_html=True)
    if live_errors:
        st.warning("Some provider reads are degraded: " + " · ".join(live_errors))

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
              <div><div class="k">Equity</div><div class="v">{money(row["equity"])}</div></div>
              <div><div class="k">Deployed</div><div class="v">{money(row["deployed"])}</div></div>
              <div><div class="k">Available</div><div class="v">{money(row["available"])}</div></div>
              <div><div class="k">Today P&L</div><div class="v {pnl_class}">{signed_money(row["today_pnl"])}</div></div>
              <div><div class="k">Daily Return</div><div class="v {pnl_class}">{signed_pct(row["daily_return"])}</div></div>
              <div><div class="k">Total P&L</div><div class="v {total_class}">{signed_money(row["total_pnl"])}</div></div>
              <div><div class="k">Realized</div><div class="v">{signed_money(row["realized"])}</div></div>
              <div><div class="k">Unrealized</div><div class="v">{signed_money(row["unrealized"])}</div></div>
              <div><div class="k">Positions</div><div class="v">{row["positions"]}</div></div>
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
