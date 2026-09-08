"""Current income-test dashboard. This app is a reader, never an order client."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import streamlit as st

from portfolio_reporting import REPORT_VERSION, build_report, fresh

ROOT = Path(__file__).resolve().parent
PUBLIC_STATUS = "https://raw.githubusercontent.com/cjhaake1-commits/trading-platform/runtime-status/runtime-status/external_status.json"


def money(value):
    return "UNAVAILABLE" if value is None else f"${value:,.2f}"


@st.cache_data(ttl=20)
def public_report():
    try:
        request = Request(PUBLIC_STATUS, headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        report = payload.get("portfolio_accounting", {})
        return report if report.get("schema_version") == REPORT_VERSION else {}
    except (OSError, ValueError, TypeError):
        return {}


@st.fragment(run_every="20s")
def current_view():
    now = datetime.now(UTC)
    local_runtime = ROOT / "var/autotrader/status.json"
    report = build_report(ROOT, now=now)
    if not local_runtime.exists():
        remote = public_report()
        if remote:
            report = remote
    runtime = report.get("runtime", {})
    recent = fresh(runtime.get("heartbeat_at"), now)
    st.caption(f"Report version: {REPORT_VERSION} | Source heartbeat: {runtime.get('heartbeat_at') or 'UNAVAILABLE'} | Refresh: 20 seconds")
    if not recent:
        st.error("Runtime telemetry is stale or unavailable. Old data is not evidence that trading is active.")
    elif runtime.get("live_trading_enabled") is not False:
        st.error("Paper-only state is not verified. This dashboard cannot authorize execution.")
    if report.get("status") != "AVAILABLE" or not fresh(report.get("observed_at"), now):
        st.warning("Portfolio accounting is incomplete or stale. Missing amounts are shown as UNAVAILABLE, not $0. The $6,000 below is the test budget, not broker equity or a reported gain.")
    complete = report.get("status") == "AVAILABLE" and fresh(report.get("observed_at"), now)
    cols = st.columns(4)
    cols[0].metric("Initial paper budget", "$6,000.00")
    for col, label, key in zip(cols[1:], ("Verified equity", "Capital deployed", "Available capital"), ("equity", "deployed", "available"), strict=True):
        col.metric(label, money(report.get(key) if complete else None))
    st.caption("$1,000 initial allocation per pillar. Provider buying power and leveraged notional are not additional invested capital.")
    pnl = st.columns(3)
    pnl[0].metric("Reported realized today", money(report.get("realized_today") if complete else None))
    pnl[1].metric("Unrealized P&L", money(report.get("unrealized") if complete else None))
    pnl[2].metric("Verified net cash income", money(report.get("net_income")))
    st.caption(report.get("realized_scope", "Income requires completed outcomes and all execution costs."))
    st.subheader("Six pillars: engine activity is not the same as transactions")
    table = []
    for row in report.get("pillars", []):
        engine = runtime.get("pillars", {}).get(row["pillar"], {})
        valid = row.get("status") == "VERIFIED" and fresh(row.get("observed_at"), now)
        table.append({"Pillar": row["pillar"], "Initial budget": 1000.0,
            "Engine": engine.get("state") if recent else "STALE / UNKNOWN",
            "Deployed": row.get("deployed") if valid else None,
            "Available": row.get("available") if valid else None,
            "Unrealized P&L": row.get("unrealized") if valid else None,
            "Reported positions": row.get("positions") if valid else None,
            "Accounting": row.get("status"), "Observed at": row.get("observed_at"),
            "Last blocker": "; ".join(engine.get("reasons", [])),
        })
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.subheader("Observed provider positions")
    if fresh(report.get("positions_observed_at"), now):
        st.caption("Provider observations may include older or unattributed holdings. They are not automatically credited to this test. Non-USD values are not summed into USD totals.")
        positions = report.get("position_observations", [])
        if positions:
            st.dataframe(positions, use_container_width=True, hide_index=True)
        else:
            st.info("No position rows in the latest observation; inspect provider coverage before treating an account as flat.")
    else:
        st.info("No fresh provider-position snapshot is available.")
    st.subheader("Actual engine order receipts — current UTC day")
    evidence = report.get("execution_evidence", {})
    if recent and evidence.get("utc_date") == now.date().isoformat():
        receipts = evidence.get("receipts", [])
        count = evidence.get("provider_order_receipts_count")
        st.metric("Distinct order receipts reported by engines", "UNAVAILABLE" if count is None else str(count))
        st.caption("An order receipt is not a confirmed fill, closed trade, strategy-owned position or earned income. Kalshi is not included in this engine-cycle count.")
        if evidence.get("latest_cycles"):
            st.dataframe(evidence["latest_cycles"], use_container_width=True, hide_index=True)
        if receipts:
            st.dataframe(receipts, use_container_width=True, hide_index=True)
        if evidence.get("window_complete") is not True:
            st.warning("Receipt history coverage is incomplete; no complete daily count can be asserted.")
    else:
        st.info("No fresh current-day execution report is available.")
    st.subheader("Income and capital-reuse evidence")
    first = report.get("first_qualifying_post_boundary_trade") or {}
    if recent and first.get("qualified") is True:
        st.json(first)
    else:
        st.write("No current verified post-boundary order/fill is available in the strict lifecycle monitor. Check engine receipts separately; missing monitor events do not prove zero activity.")
    st.write("Target: short-duration, cost-positive paper trades; realized net cash; released and redeployed capital. Transaction volume, margin borrowing and unrealized gains are not income.")
    st.caption("Short sales, options and leveraged strategies require verified provider support and existing risk controls. This app cannot enable live trading.")
    with st.expander("Accounting diagnostics and partial observations"):
        st.json(report)


def main():
    st.set_page_config(page_title="Trading Platform | Income Test", page_icon="◈", layout="wide")
    st.title("Trading Platform — $6,000 Income Test")
    st.caption("PAPER / PRACTICE / SIM / DEMO | Observation only")
    if st.button("Refresh current data"):
        public_report.clear()
        st.rerun()
    current_view()


if __name__ == "__main__":
    main()
