from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

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


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@st.cache_data(ttl=20)
def load_snapshot() -> dict[str, object]:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value).strip()


def fetch_live_broker_data() -> tuple[list[dict[str, object]], dict[str, float], dict[str, dict[str, object]], list[str]]:
    positions: list[dict[str, object]] = []
    metrics = {"unrealized_pnl": 0.0, "gross_exposure": 0.0, "alpaca_exposure": 0.0, "oanda_exposure": 0.0}
    broker_status = {
        "alpaca": {"connected": False, "positions": 0, "state": "CHECK", "unrealized_pnl": 0.0},
        "oanda": {"connected": False, "positions": 0, "state": "CHECK", "unrealized_pnl": 0.0},
    }
    errors: list[str] = []

    alpaca_key = _secret("ALPACA_PAPER_API_KEY")
    alpaca_secret = _secret("ALPACA_PAPER_SECRET_KEY")
    alpaca_base = _secret("ALPACA_PAPER_BASE_URL") or "https://paper-api.alpaca.markets"
    if alpaca_key and alpaca_secret:
        try:
            req = Request(
                f"{alpaca_base.rstrip('/')}/v2/positions",
                headers={
                    "APCA-API-KEY-ID": alpaca_key,
                    "APCA-API-SECRET-KEY": alpaca_secret,
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=10) as r:
                rows = json.load(r)
            rows = rows if isinstance(rows, list) else []
            broker_status["alpaca"]["connected"] = True
            broker_status["alpaca"]["positions"] = len(rows)
            broker_status["alpaca"]["state"] = "TRADING" if rows else "FLAT"
            for row in rows:
                qty = _float(row.get("qty"))
                avg = _float(row.get("avg_entry_price"))
                current = _float(row.get("current_price"), avg)
                market_value = abs(_float(row.get("market_value"), qty * current))
                unrealized = _float(row.get("unrealized_pl"))
                positions.append(
                    {
                        "broker": "Alpaca Paper",
                        "symbol": row.get("symbol"),
                        "quantity": qty,
                        "average_price": avg,
                        "current_price": current,
                        "market_value": market_value,
                        "unrealized_pnl": unrealized,
                        "unrealized_pct": _float(row.get("unrealized_plpc")),
                    }
                )
                metrics["unrealized_pnl"] += unrealized
                metrics["gross_exposure"] += market_value
                metrics["alpaca_exposure"] += market_value
                broker_status["alpaca"]["unrealized_pnl"] += unrealized
        except Exception as exc:
            errors.append(f"Alpaca live read failed: {exc}")
    else:
        errors.append("Alpaca Streamlit secrets are not configured")

    oanda_token = _secret("OANDA_PRACTICE_TOKEN")
    oanda_account = _secret("OANDA_PRACTICE_ACCOUNT_ID")
    oanda_base = _secret("OANDA_PRACTICE_BASE_URL") or "https://api-fxpractice.oanda.com"
    if oanda_token and oanda_account:
        try:
            req = Request(
                f"{oanda_base.rstrip('/')}/v3/accounts/{oanda_account}/openPositions",
                headers={"Authorization": f"Bearer {oanda_token}", "Accept": "application/json"},
            )
            with urlopen(req, timeout=10) as r:
                payload = json.load(r)
            rows = payload.get("positions", []) if isinstance(payload, dict) else []
            broker_status["oanda"]["connected"] = True
            broker_status["oanda"]["positions"] = len(rows)
            broker_status["oanda"]["state"] = "TRADING" if rows else "FLAT"
            for row in rows:
                symbol = str(row.get("instrument") or "").replace("_", "/")
                long = row.get("long") if isinstance(row.get("long"), dict) else {}
                short = row.get("short") if isinstance(row.get("short"), dict) else {}
                long_units = _float(long.get("units"))
                short_units = _float(short.get("units"))
                qty = long_units + short_units
                side = long if abs(long_units) >= abs(short_units) else short
                avg = _float(side.get("averagePrice"))
                unrealized = _float(row.get("unrealizedPL"))
                exposure = abs(qty * avg)
                positions.append(
                    {
                        "broker": "OANDA Practice",
                        "symbol": symbol,
                        "quantity": qty,
                        "average_price": avg,
                        "current_price": None,
                        "market_value": exposure,
                        "unrealized_pnl": unrealized,
                        "unrealized_pct": None,
                    }
                )
                metrics["unrealized_pnl"] += unrealized
                metrics["gross_exposure"] += exposure
                metrics["oanda_exposure"] += exposure
                broker_status["oanda"]["unrealized_pnl"] += unrealized
        except Exception as exc:
            errors.append(f"OANDA live read failed: {exc}")
    else:
        errors.append("OANDA Streamlit secrets are not configured")

    return positions, metrics, broker_status, errors


st.title("Autonomous Trading Command Center")
st.caption("Alpaca Paper + OANDA Practice · autonomous testing · broker data refreshes about every 30 seconds")

data = load_snapshot() or {}
runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
guardrails = data.get("guardrails") if isinstance(data.get("guardrails"), dict) else {}
targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
activity = data.get("activity") if isinstance(data.get("activity"), list) else []
cycle = data.get("latest_cycle") if isinstance(data.get("latest_cycle"), dict) else {}
base_equity = _float((data.get("portfolio") or {}).get("base_equity"), 2000.0) if isinstance(data.get("portfolio"), dict) else 2000.0


@st.fragment(run_every="30s")
def live_panel() -> None:
    positions, metrics, broker_status, errors = fetch_live_broker_data()
    open_pnl = metrics["unrealized_pnl"]
    marked_equity = base_equity + open_pnl
    mtm_return = (marked_equity - base_equity) / base_equity if base_equity else 0.0

    st.subheader("Live broker results")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Live broker feed", "CONNECTED" if broker_status["alpaca"]["connected"] or broker_status["oanda"]["connected"] else "CHECK")
    c2.metric("Marked equity", _money(marked_equity))
    c3.metric("Open P&L", _money(open_pnl))
    c4.metric("MTM return", _pct(mtm_return))
    c5.metric("Gross exposure", _money(metrics["gross_exposure"]))
    c6.metric("Open positions", len(positions))

    st.markdown("**Broker status**")
    b1, b2 = st.columns(2)
    with b1:
        st.metric("Alpaca Paper", f"{'CONNECTED' if broker_status['alpaca']['connected'] else 'CHECK'} · {broker_status['alpaca']['state']}")
        st.caption(f"Positions: {broker_status['alpaca']['positions']} · Exposure: {_money(metrics['alpaca_exposure'])} · Open P&L: {_money(broker_status['alpaca']['unrealized_pnl'])}")
    with b2:
        st.metric("OANDA Practice", f"{'CONNECTED' if broker_status['oanda']['connected'] else 'CHECK'} · {broker_status['oanda']['state']}")
        st.caption(f"Positions: {broker_status['oanda']['positions']} · Exposure: {_money(metrics['oanda_exposure'])} · Open P&L: {_money(broker_status['oanda']['unrealized_pnl'])}")

    if errors:
        with st.expander("Live feed status"):
            for error in errors:
                st.write(error)

    if positions:
        st.table([
            {
                "Broker": row.get("broker"),
                "Symbol": row.get("symbol"),
                "Qty": _number(row.get("quantity"), 4),
                "Entry": _money(row.get("average_price")),
                "Current": _money(row.get("current_price")),
                "Market value": _money(row.get("market_value")),
                "Open P&L": _money(row.get("unrealized_pnl")),
                "Return": _pct(row.get("unrealized_pct")),
            }
            for row in positions
        ])
    else:
        st.info("No open positions returned by the brokers.")

    st.caption("Live broker values refresh automatically about every 30 seconds while this page is open.")


live_panel()

st.subheader("Stretch target vs guardrails")
t1, t2, t3, t4 = st.columns(4)
t1.metric("Stretch benchmark", "20–30% / day")
t2.metric("Risk / trade", _pct(guardrails.get("risk_per_trade_pct")))
t3.metric("Daily loss stop", _pct(guardrails.get("max_daily_loss_pct")))
t4.metric("Max drawdown", _pct(guardrails.get("max_peak_drawdown_pct")))
st.caption(str(targets.get("note") or "Stretch benchmark only; risk controls remain authoritative."))

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
    st.info("Decision-cycle details come from the last VM snapshot; live broker positions above do not depend on that snapshot.")

with st.expander("Runtime snapshot", expanded=False):
    st.write({
        "mode": runtime.get("mode"),
        "last_heartbeat_at": runtime.get("last_heartbeat_at"),
        "published_at": data.get("published_at"),
        "last_cycle_started_at": runtime.get("last_cycle_started_at"),
        "last_cycle_finished_at": runtime.get("last_cycle_finished_at"),
        "autonomous_job_disabled": runtime.get("autonomous_job_disabled"),
        "consecutive_failures": runtime.get("consecutive_failures"),
        "last_error": runtime.get("last_error"),
    })

st.subheader("Recent autonomous activity snapshot")
if activity:
    st.table([{"Time": row.get("time"), "Event": row.get("event"), "Message": row.get("message")} for row in activity[:40]])
else:
    st.info("No activity snapshot published yet.")

st.caption("Paper/practice trading only. Live broker reads use Streamlit Secrets and are not stored in the repository or rendered in the page source.")
