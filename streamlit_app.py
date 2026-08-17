from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

import streamlit as st

st.set_page_config(page_title="Autonomous Trading Command Center", page_icon="📈", layout="wide")
DATA_PATH = Path("dashboard/data.json")
TOTAL_BASE_CAPITAL = 3000.0
PILLAR_BASE_CAPITAL = 1000.0


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
    metrics = {
        "unrealized_pnl": 0.0,
        "gross_exposure": 0.0,
        "equity_exposure": 0.0,
        "crypto_exposure": 0.0,
        "oanda_exposure": 0.0,
    }
    pillar_status = {
        "equities": {"connected": False, "positions": 0, "state": "CHECK", "unrealized_pnl": 0.0},
        "crypto": {"connected": False, "positions": 0, "state": "CHECK", "unrealized_pnl": 0.0},
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
            pillar_status["equities"]["connected"] = True
            pillar_status["crypto"]["connected"] = True

            for row in rows:
                asset_class = str(row.get("asset_class") or "").lower()
                is_crypto = asset_class == "crypto"
                pillar = "crypto" if is_crypto else "equities"
                qty = _float(row.get("qty"))
                avg = _float(row.get("avg_entry_price"))
                current = _float(row.get("current_price"), avg)
                market_value = abs(_float(row.get("market_value"), qty * current))
                unrealized = _float(row.get("unrealized_pl"))
                positions.append(
                    {
                        "pillar": "Alpaca Crypto" if is_crypto else "Alpaca Equities",
                        "broker": "Alpaca Paper",
                        "asset_class": asset_class or "us_equity",
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
                metrics["crypto_exposure" if is_crypto else "equity_exposure"] += market_value
                pillar_status[pillar]["positions"] += 1
                pillar_status[pillar]["unrealized_pnl"] += unrealized

            for pillar in ("equities", "crypto"):
                pillar_status[pillar]["state"] = "TRADING" if pillar_status[pillar]["positions"] else "FLAT"
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
            pillar_status["oanda"]["connected"] = True
            pillar_status["oanda"]["positions"] = len(rows)
            pillar_status["oanda"]["state"] = "TRADING" if rows else "FLAT"
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
                        "pillar": "OANDA FX",
                        "broker": "OANDA Practice",
                        "asset_class": "forex",
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
                pillar_status["oanda"]["unrealized_pnl"] += unrealized
        except Exception as exc:
            errors.append(f"OANDA live read failed: {exc}")
    else:
        errors.append("OANDA Streamlit secrets are not configured")

    return positions, metrics, pillar_status, errors


st.title("Autonomous Trading Command Center")
st.caption("$3,000 paper portfolio · $1,000 per pillar · Alpaca Equities · OANDA FX · Alpaca Crypto · live broker data refreshes about every 30 seconds")

data = load_snapshot() or {}
runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
guardrails = data.get("guardrails") if isinstance(data.get("guardrails"), dict) else {}
targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
activity = data.get("activity") if isinstance(data.get("activity"), list) else []
cycle = data.get("latest_cycle") if isinstance(data.get("latest_cycle"), dict) else {}
base_equity = TOTAL_BASE_CAPITAL


@st.fragment(run_every="30s")
def live_panel() -> None:
    positions, metrics, pillar_status, errors = fetch_live_broker_data()
    open_pnl = metrics["unrealized_pnl"]
    marked_equity = base_equity + open_pnl
    mtm_return = open_pnl / base_equity if base_equity else 0.0

    st.subheader("Live portfolio")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Starting capital", _money(base_equity))
    c2.metric("Marked equity", _money(marked_equity))
    c3.metric("Open P&L", _money(open_pnl))
    c4.metric("MTM return", _pct(mtm_return))
    c5.metric("Gross exposure", _money(metrics["gross_exposure"]))
    c6.metric("Open positions", len(positions))

    st.subheader("Trading pillars")
    p1, p2, p3 = st.columns(3)
    with p1:
        status = pillar_status["equities"]
        pillar_equity = PILLAR_BASE_CAPITAL + _float(status["unrealized_pnl"])
        st.metric("Alpaca Equities", f"{'CONNECTED' if status['connected'] else 'CHECK'} · {status['state']}")
        st.caption(f"Base: {_money(PILLAR_BASE_CAPITAL)} · Marked: {_money(pillar_equity)} · Positions: {status['positions']} · Exposure: {_money(metrics['equity_exposure'])} · P&L: {_money(status['unrealized_pnl'])}")
    with p2:
        status = pillar_status["oanda"]
        pillar_equity = PILLAR_BASE_CAPITAL + _float(status["unrealized_pnl"])
        st.metric("OANDA FX", f"{'CONNECTED' if status['connected'] else 'CHECK'} · {status['state']}")
        st.caption(f"Base: {_money(PILLAR_BASE_CAPITAL)} · Marked: {_money(pillar_equity)} · Positions: {status['positions']} · Exposure: {_money(metrics['oanda_exposure'])} · P&L: {_money(status['unrealized_pnl'])}")
    with p3:
        status = pillar_status["crypto"]
        pillar_equity = PILLAR_BASE_CAPITAL + _float(status["unrealized_pnl"])
        st.metric("Alpaca Crypto", f"{'CONNECTED' if status['connected'] else 'CHECK'} · {status['state']}")
        st.caption(f"Base: {_money(PILLAR_BASE_CAPITAL)} · Marked: {_money(pillar_equity)} · Positions: {status['positions']} · Exposure: {_money(metrics['crypto_exposure'])} · P&L: {_money(status['unrealized_pnl'])}")

    if errors:
        with st.expander("Live feed status"):
            for error in errors:
                st.write(error)

    st.subheader("Open positions by pillar")
    if positions:
        st.table([
            {
                "Pillar": row.get("pillar"),
                "Symbol": row.get("symbol"),
                "Qty": _number(row.get("quantity"), 6 if row.get("asset_class") == "crypto" else 4),
                "Entry": _money(row.get("average_price")),
                "Current": _money(row.get("current_price")),
                "Market value": _money(row.get("market_value")),
                "Open P&L": _money(row.get("unrealized_pnl")),
                "Return": _pct(row.get("unrealized_pct")),
            }
            for row in positions
        ])
    else:
        st.info("All three pillars are currently flat.")

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

    c1, c2, c3 = st.columns(3)
    c1.metric("Equity qualified", cycle.get("equity_qualified", "—"))
    c2.metric("FX qualified", cycle.get("forex_qualified", "—"))
    c3.metric("Crypto qualified", cycle.get("crypto_qualified", "—"))

    candidates = cycle.get("top_candidates") if isinstance(cycle.get("top_candidates"), list) else []
    if candidates:
        st.markdown("**Top candidates**")
        st.table([
            {
                "Symbol": row.get("symbol"),
                "Asset": row.get("asset_class", "—"),
                "Score": row.get("score"),
                "Momentum": f"{row.get('momentum_pct')}%" if row.get("momentum_pct") is not None else "—",
                "Last": _money(row.get("last_price")),
            }
            for row in candidates[:10]
        ])
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

st.caption("Paper/practice trading only. Three independent $1,000 pillars roll up to one $3,000 paper portfolio. Live broker reads use Streamlit Secrets and are never stored in the repository.")
