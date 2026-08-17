from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Autonomous Paper Trading", page_icon="📈", layout="wide")

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


@st.cache_data(ttl=30)
def load_snapshot() -> dict[str, object]:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


st.title("Autonomous Paper Trading")
st.caption("Combined Alpaca Paper + OANDA Practice")

data = load_snapshot()
if not data:
    st.warning("No dashboard snapshot has been published yet from the trading VM.")
    st.stop()

runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
portfolio = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
guardrails = data.get("guardrails") if isinstance(data.get("guardrails"), dict) else {}
positions = data.get("positions") if isinstance(data.get("positions"), list) else []
activity = data.get("activity") if isinstance(data.get("activity"), list) else []

published_at = data.get("published_at")
heartbeat = runtime.get("last_heartbeat_at")
healthy = bool(runtime.get("healthy"))

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Runtime", "RUNNING" if healthy else "CHECK")
c2.metric("Portfolio equity", _money(portfolio.get("equity")))
c3.metric("Daily P&L", _money(portfolio.get("daily_pnl")))
c4.metric("Weekly P&L", _money(portfolio.get("weekly_pnl")))
c5.metric("Drawdown", _pct(portfolio.get("drawdown_pct")))
c6.metric("Open positions", len(positions))

st.subheader("Guardrails")
g1, g2, g3, g4 = st.columns(4)
g1.metric("Risk / trade", _pct(guardrails.get("risk_per_trade_pct")))
g2.metric("Daily loss stop", _pct(guardrails.get("max_daily_loss_pct")))
g3.metric("Max drawdown", _pct(guardrails.get("max_peak_drawdown_pct")))
g4.metric("Recorded fills", data.get("fill_count", 0))

with st.expander("Runtime health", expanded=True):
    st.write(
        {
            "mode": runtime.get("mode"),
            "last_heartbeat_at": heartbeat,
            "published_at": published_at,
            "autonomous_job_disabled": runtime.get("autonomous_job_disabled"),
            "consecutive_failures": runtime.get("consecutive_failures"),
            "last_error": runtime.get("last_error"),
        }
    )

st.subheader("Open positions")
if positions:
    st.table(
        [
            {
                "Broker": row.get("broker"),
                "Symbol": row.get("symbol"),
                "Asset": row.get("asset_class"),
                "Quantity": row.get("quantity"),
                "Avg price": row.get("average_price"),
                "Stop": row.get("stop_price"),
            }
            for row in positions
        ]
    )
else:
    st.info("No open positions.")

st.subheader("Recent autonomous activity")
if activity:
    st.table(
        [
            {
                "Time": row.get("time"),
                "Event": row.get("event"),
                "Message": row.get("message"),
            }
            for row in activity[:50]
        ]
    )
else:
    st.info("No activity published yet.")

st.caption(
    "Paper/practice trading only. This app reads a sanitized snapshot and does not contain broker keys, secrets, or account IDs."
)
