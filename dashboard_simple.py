from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

import streamlit_app as legacy

st.set_page_config(page_title="Trading Platform", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")


def money(value: object) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def simple_status(value: object) -> str:
    text = str(value or "").upper()
    if any(x in text for x in ("ERROR", "DEGRADED", "AUTH")):
        return "ERROR"
    if any(x in text for x in ("WAIT", "CLOSED")):
        return "WAITING FOR MARKET"
    if any(x in text for x in ("SHADOW", "LEARNING", "QUARANT")):
        return "LEARNING"
    if any(x in text for x in ("TRADING", "POSITION", "ORDER", "ACTIVE")):
        return "ACTIVE"
    if any(x in text for x in ("SCAN", "READY", "EVALUAT")):
        return "SCANNING"
    return "SCANNING"


def main() -> None:
    st.markdown("# Autonomous Trading Platform")
    top_a, top_b, top_c = st.columns([2, 1, 1])
    top_a.caption("PAPER / PRACTICE / SIM / DEMO · LIVE MONEY OFF")
    top_b.caption("AUTO REFRESH: OFF")
    if top_c.button("Refresh Now", use_container_width=True):
        legacy.fetch_live_broker_data.clear()
        st.rerun()

    ctx = legacy._build_dashboard_context()
    snapshot = ctx.get("snapshot", {}) if isinstance(ctx, dict) else {}
    fund = ctx.get("fund", {}) if isinstance(ctx, dict) else {}
    pillars = ctx.get("pillars", []) if isinstance(ctx, dict) else []
    positions = ctx.get("positions", []) if isinstance(ctx, dict) else []
    forward = ctx.get("forward_evidence", {}) if isinstance(ctx, dict) else {}

    data_as_of = snapshot.get("as_of") or snapshot.get("timestamp") or ctx.get("as_of") or datetime.now(UTC).isoformat()
    st.caption(f"DATA AS OF: {data_as_of}")

    economic_capital = number(fund.get("authorized_capital", 6000.0)) or 6000.0
    equity = number(fund.get("economic_equity", fund.get("equity", economic_capital)))
    committed = number(fund.get("committed_capital", fund.get("committed", 0.0)))
    available = number(fund.get("available_capital", economic_capital - committed))
    realized = number(fund.get("realized_pnl", 0.0))
    unrealized = number(fund.get("unrealized_pnl", equity - economic_capital - realized))
    total_pnl = realized + unrealized
    utilization = committed / economic_capital if economic_capital else 0.0

    st.markdown("## Portfolio")
    cols = st.columns(5)
    cols[0].metric("Economic Capital", money(economic_capital))
    cols[1].metric("Current Equity", money(equity), money(total_pnl))
    cols[2].metric("Capital Deployed", money(committed))
    cols[3].metric("Capital Available", money(available))
    cols[4].metric("Utilization", f"{utilization:.1%}")
    cols = st.columns(4)
    cols[0].metric("Total P&L", money(total_pnl))
    cols[1].metric("Realized P&L", money(realized))
    cols[2].metric("Unrealized P&L", money(unrealized))
    completed = int(number(forward.get("completed_outcomes", forward.get("completed", 0))))
    cols[3].metric("Forward Outcomes", completed)

    st.markdown("## Six Pillars")
    pillar_names = ["US Stocks / ETFs", "Crypto", "Forex", "Metals / Commodities", "International", "Kalshi"]
    lookup = {str(p.get("name") or p.get("pillar")): p for p in pillars if isinstance(p, dict)}
    engaged = 0
    owned_total = 0
    for start in (0, 3):
        row = st.columns(3)
        for col, name in zip(row, pillar_names[start:start + 3], strict=True):
            p = lookup.get(name, {})
            status = simple_status(p.get("state") or p.get("status"))
            if status not in {"ERROR"}:
                engaged += 1
            owned = int(number(p.get("platform_owned_positions", p.get("positions", 0))))
            owned_total += int(owned > 0)
            auth = number(p.get("authorized_capital", 1000.0)) or 1000.0
            dep = number(p.get("committed_capital", p.get("committed", 0.0)))
            avail = number(p.get("available_capital", auth - dep))
            pnl = number(p.get("realized_pnl", 0.0)) + number(p.get("unrealized_pnl", 0.0))
            with col.container(border=True):
                st.markdown(f"### {name.replace('US Stocks / ETFs', 'Stocks')}")
                st.markdown(f"**{status}**")
                st.write(f"Positions: **{owned} owned**")
                st.write(f"Deployed: **{money(dep)} / {money(auth)}**")
                st.write(f"Available: **{money(avail)}**")
                st.write(f"P&L: **{money(pnl)}**")
                bottleneck = p.get("bottleneck") or p.get("reason") or p.get("message")
                if bottleneck:
                    st.caption(str(bottleneck)[:140])

    st.info(f"Pillars engaged: {engaged}/6   ·   Pillars with platform-owned positions: {owned_total}/6")

    st.markdown("## Current Positions")
    if positions:
        rows = []
        for p in positions:
            if not isinstance(p, dict):
                continue
            rows.append({
                "Pillar": p.get("pillar", "—"),
                "Symbol": p.get("symbol", p.get("instrument", "—")),
                "Side": p.get("side", "—"),
                "Size": p.get("quantity", p.get("qty", "—")),
                "Value": p.get("market_value", p.get("current_value", "—")),
                "P&L": p.get("unrealized_pnl", "—"),
                "Ownership": p.get("ownership", p.get("ownership_state", "UNKNOWN")),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No reconciled position rows available in the loaded snapshot.")

    st.markdown("## Returns")
    ret_cols = st.columns(4)
    ret_cols[0].metric("Portfolio P&L", money(total_pnl))
    ret_cols[1].metric("Portfolio Return", f"{(total_pnl / economic_capital):.2%}" if economic_capital else "—")
    ret_cols[2].metric("Forward Sample", completed)
    ret_cols[3].metric("Forward Strategy Return", "INSUFFICIENT DATA" if completed == 0 else str(forward.get("return_pct", "—")))

    st.markdown("## What the platform is doing now")
    action_rows = []
    for name in pillar_names:
        p = lookup.get(name, {})
        action_rows.append({"Pillar": name.replace("US Stocks / ETFs", "Stocks"), "Current Action": simple_status(p.get("state") or p.get("status"))})
    st.dataframe(action_rows, use_container_width=True, hide_index=True)

    with st.expander("Advanced Details", expanded=False):
        choice = st.selectbox("Show", ["Provider Status", "Engine Funnel", "Risk & Health", "Learning", "Performance", "Execution Log"])
        if choice == "Provider Status":
            legacy._render_risk_health_view(ctx)
        elif choice == "Engine Funnel":
            legacy._render_pillars_view(ctx)
        elif choice == "Risk & Health":
            legacy._render_risk_health_view(ctx)
        elif choice == "Learning":
            legacy._render_learning_view(ctx)
        elif choice == "Performance":
            legacy._render_performance_view(ctx)
        elif choice == "Execution Log":
            legacy._render_execution_log_view(ctx)


if __name__ == "__main__":
    main()
