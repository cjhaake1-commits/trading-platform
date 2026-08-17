from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Autonomous Trading Command Center", page_icon="📈", layout="wide")
DATA_PATH = Path("dashboard/data.json")


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "—"


def _pct(value) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "—"


def _number(value, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "—"


@st.cache_data(ttl=20)
def load_snapshot() -> dict[str, object]:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


st.title("Autonomous Trading Command Center")
st.caption("Alpaca Paper + OANDA Practice · autonomous testing · sanitized broker data")

data = load_snapshot()
if not data:
    st.warning("No dashboard snapshot has been published yet from the trading VM.")
    st.stop()

runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
portfolio = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
guardrails = data.get("guardrails") if isinstance(data.get("guardrails"), dict) else {}
targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
positions = data.get("positions") if isinstance(data.get("positions"), list) else []
activity = data.get("activity") if isinstance(data.get("activity"), list) else []
cycle = data.get("latest_cycle") if isinstance(data.get("latest_cycle"), dict) else {}

healthy = bool(runtime.get("healthy"))

st.subheader("Live testing scorecard")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Runtime", "RUNNING" if healthy else "CHECK")
c2.metric("Marked equity", _money(portfolio.get("marked_equity")))
c3.metric("Open P&L", _money(portfolio.get("open_unrealized_pnl")))
c4.metric("MTM return", _pct(portfolio.get("mtm_return_pct")))
c5.metric("Gross exposure", _money(portfolio.get("gross_exposure")))
c6.metric("Open positions", len(positions))

st.subheader("Stretch target vs guardrails")
t1, t2, t3, t4, t5 = st.columns(5)
t1.metric("Stretch benchmark", "20–30% / day")
t2.metric("Progress to 20%", _pct(targets.get("progress_to_low")))
t3.metric("Risk / trade", _pct(guardrails.get("risk_per_trade_pct")))
t4.metric("Daily loss stop", _pct(guardrails.get("max_daily_loss_pct")))
t5.metric("Max drawdown", _pct(guardrails.get("max_peak_drawdown_pct")))
st.caption(str(targets.get("note") or "Stretch benchmark only; risk controls remain authoritative."))

r1, r2, r3, r4 = st.columns(4)
r1.metric("Open risk", _money(portfolio.get("open_risk_dollars")))
r2.metric("Current drawdown", _pct(portfolio.get("drawdown_pct")))
r3.metric("Alpaca exposure", _money(portfolio.get("alpaca_exposure")))
r4.metric("OANDA exposure", _money(portfolio.get("oanda_exposure")))

st.subheader("Open broker positions")
if positions:
    st.table([
        {
            "Broker": row.get("broker"),
            "Symbol": row.get("symbol"),
            "Qty": _number(row.get("quantity"), 4),
            "Entry": _money(row.get("average_price")),
            "Current": _money(row.get("current_price")),
            "Stop": _money(row.get("stop_price")),
            "Market value": _money(row.get("market_value")),
            "Open P&L": _money(row.get("unrealized_pnl")),
            "Return": _pct(row.get("unrealized_pct")),
            "Risk to stop": _money(row.get("risk_dollars")),
        }
        for row in positions
    ])
else:
    st.info("No open broker positions.")

st.subheader("Latest autonomous decision cycle")
if cycle:
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Scanned", cycle.get("scanned", "—"))
    d2.metric("Qualified", cycle.get("qualified_signals", "—"))
    d3.metric("Entries", len(cycle.get("entries", []) or []))
    rejection_count = len(cycle.get("risk_rejections", []) or []) + len(cycle.get("submission_failures", []) or []) + len(cycle.get("sizing_skips", []) or [])
    d4.metric("Rejected / skipped", rejection_count)

    candidates = cycle.get("top_candidates") if isinstance(cycle.get("top_candidates"), list) else []
    if candidates:
        st.markdown("**Top candidates**")
        st.table([
            {
                "Symbol": row.get("symbol"),
                "Score": row.get("score"),
                "Momentum": f"{row.get('momentum_pct')}%" if row.get("momentum_pct") is not None else "—",
                "Last": _money(row.get("last_price")),
            }
            for row in candidates[:10]
        ])

    entries = cycle.get("entries") if isinstance(cycle.get("entries"), list) else []
    if entries:
        st.markdown("**Accepted entries**")
        st.json(entries, expanded=False)

    failures = cycle.get("submission_failures") if isinstance(cycle.get("submission_failures"), list) else []
    risk_rejections = cycle.get("risk_rejections") if isinstance(cycle.get("risk_rejections"), list) else []
    sizing_skips = cycle.get("sizing_skips") if isinstance(cycle.get("sizing_skips"), list) else []
    duplicate_skips = cycle.get("duplicate_skips") if isinstance(cycle.get("duplicate_skips"), list) else []
    if failures or risk_rejections or sizing_skips or duplicate_skips:
        with st.expander("Decision rejects / skips"):
            if failures:
                st.write("Submission failures", failures)
            if risk_rejections:
                st.write("Risk rejections", risk_rejections)
            if sizing_skips:
                st.write("Sizing skips", sizing_skips)
            if duplicate_skips:
                st.write("Duplicate skips", duplicate_skips)
else:
    st.info("No autonomous cycle details have been published yet.")

with st.expander("Runtime health", expanded=False):
    st.write({
        "mode": runtime.get("mode"),
        "last_heartbeat_at": runtime.get("last_heartbeat_at"),
        "published_at": data.get("published_at"),
        "last_cycle_started_at": runtime.get("last_cycle_started_at"),
        "last_cycle_finished_at": runtime.get("last_cycle_finished_at"),
        "last_cycle_duration_ms": runtime.get("last_cycle_duration_ms"),
        "autonomous_job_disabled": runtime.get("autonomous_job_disabled"),
        "consecutive_failures": runtime.get("consecutive_failures"),
        "last_error": runtime.get("last_error"),
    })

st.subheader("Recent autonomous activity")
if activity:
    st.table([{"Time": row.get("time"), "Event": row.get("event"), "Message": row.get("message")} for row in activity[:40]])
else:
    st.info("No activity published yet.")

st.caption("Paper/practice trading only. Stretch returns are evaluation benchmarks, not guaranteed outcomes or instructions to override risk limits. Broker keys, secrets, and account IDs are never published to this dashboard.")
