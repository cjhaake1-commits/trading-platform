from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st

from autotrader.broker_environment import require_alpaca_paper_url, require_oanda_practice_url
from autotrader.dashboard_health import runtime_status_labels

st.set_page_config(
    page_title="Chris Haake Capital Systems",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_PATH = Path("dashboard/data.json")
TOTAL_BASE_CAPITAL = 5000.0
PILLAR_BASE_CAPITAL = 1000.0
PILLARS = (
    ("US Stocks / ETFs", "Alpaca PAPER", "blue"),
    ("Forex", "OANDA Practice", "green"),
    ("Crypto", "Alpaca PAPER", "purple"),
    ("Metals / Commodities", "Alpaca PAPER", "gold"),
    ("International", "Saxo SIM", "teal"),
)
METALS_UNIVERSE = {"GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL"}


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


def _age_label(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "DEFERRED"
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "DEFERRED"
    if observed.tzinfo is None:
        return "DEFERRED"
    age = datetime.now(UTC) - observed.astimezone(UTC)
    if age.total_seconds() < 0:
        return "LIVE"
    if age.total_seconds() < 45:
        return f"FRESH · {int(age.total_seconds())}s"
    return f"STALE · {int(age.total_seconds())}s"


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value).strip()


def _safe_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


@st.cache_data(ttl=20)
def load_snapshot() -> dict[str, object]:
    return _safe_json(DATA_PATH)


def _pillars_from_snapshot(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    performance = snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
    result: dict[str, dict[str, object]] = {
        name: {
            "name": name,
            "broker": broker,
            "accent": accent,
            "cap": PILLAR_BASE_CAPITAL,
            "deployed": 0.0,
            "available": PILLAR_BASE_CAPITAL,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "positions": 0,
            "completed_trades": 0,
            "win_rate": None,
            "expectancy": None,
            "last_scan": "DEFERRED",
            "last_decision": "DEFERRED",
            "connection": "DEFERRED",
            "scanner": "DEFERRED",
            "status": "HOLDING CASH",
        }
        for name, broker, accent in PILLARS
    }

    broker_map = {
        "US Stocks / ETFs": "Alpaca Paper",
        "Crypto": "Alpaca Paper",
        "Metals / Commodities": "Alpaca Paper",
        "Forex": "OANDA Practice",
        "International": "Saxo SIM",
    }
    for row in positions:
        if not isinstance(row, dict):
            continue
        pillar = str(row.get("pillar") or "")
        if pillar not in result:
            if str(row.get("broker") or "").lower().startswith("alpaca") and str(row.get("symbol") or "").upper() in METALS_UNIVERSE:
                pillar = "Metals / Commodities"
            elif str(row.get("broker") or "").lower().startswith("alpaca"):
                pillar = "US Stocks / ETFs" if not str(row.get("asset_class") or "").lower() == "crypto" else "Crypto"
            elif str(row.get("broker") or "").lower().startswith("oanda"):
                pillar = "Forex"
            else:
                pillar = "International"
        metrics = result[pillar]
        market_value = abs(_float(row.get("market_value") or row.get("notional")))
        metrics["deployed"] += market_value
        metrics["unrealized_pnl"] += _float(row.get("unrealized_pnl"))
        metrics["positions"] += 1
        metrics["status"] = "TRADING" if market_value > 0 else "FLAT"
    for name, metrics in result.items():
        perf = performance.get(name) if isinstance(performance, dict) else {}
        if not isinstance(perf, dict):
            perf = {}
        metrics["realized_pnl"] = _float(perf.get("realized_pnl"))
        metrics["completed_trades"] = int(_float(perf.get("completed_trades"), 0.0))
        metrics["win_rate"] = perf.get("win_rate")
        metrics["expectancy"] = perf.get("expectancy")
        metrics["last_scan"] = perf.get("last_scan_at") or metrics["last_scan"]
        metrics["last_decision"] = perf.get("last_decision") or metrics["last_decision"]
        metrics["connection"] = perf.get("connection_status") or metrics["connection"]
        metrics["scanner"] = perf.get("scanner_status") or metrics["scanner"]
        metrics["available"] = max(PILLAR_BASE_CAPITAL - metrics["deployed"], 0.0)
        if metrics["positions"] == 0 and metrics["status"] == "HOLDING CASH":
            metrics["status"] = "FLAT"
    return result


def _secret_warning(name: str) -> str:
    return "Configured" if _secret(name) else "Not configured"


@st.cache_data(ttl=20)
def fetch_live_broker_data() -> tuple[list[dict[str, object]], dict[str, float], dict[str, dict[str, object]], list[str]]:
    positions: list[dict[str, object]] = []
    metrics = {
        "unrealized_pnl": 0.0,
        "gross_exposure": 0.0,
        "equity_exposure": 0.0,
        "crypto_exposure": 0.0,
        "metals_exposure": 0.0,
        "oanda_exposure": 0.0,
        "alpaca_exposure": 0.0,
    }
    pillar_status = {
        "US Stocks / ETFs": {"connected": False, "positions": 0, "state": "DEFERRED", "unrealized_pnl": 0.0},
        "Crypto": {"connected": False, "positions": 0, "state": "DEFERRED", "unrealized_pnl": 0.0},
        "Metals / Commodities": {"connected": False, "positions": 0, "state": "DEFERRED", "unrealized_pnl": 0.0},
        "Forex": {"connected": False, "positions": 0, "state": "DEFERRED", "unrealized_pnl": 0.0},
        "International": {"connected": False, "positions": 0, "state": "DEFERRED", "unrealized_pnl": 0.0},
    }
    errors: list[str] = []

    alpaca_key = _secret("ALPACA_PAPER_API_KEY")
    alpaca_secret = _secret("ALPACA_PAPER_SECRET_KEY")
    alpaca_base = require_alpaca_paper_url(
        _secret("ALPACA_PAPER_BASE_URL") or "https://paper-api.alpaca.markets"
    )
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
            pillar_status["US Stocks / ETFs"]["connected"] = True
            pillar_status["Crypto"]["connected"] = True
            pillar_status["Metals / Commodities"]["connected"] = True
            for row in rows:
                asset_class = str(row.get("asset_class") or "").lower()
                is_crypto = asset_class == "crypto"
                symbol = str(row.get("symbol") or "").upper()
                is_metal = symbol in METALS_UNIVERSE and not is_crypto
                pillar = "Crypto" if is_crypto else ("Metals / Commodities" if is_metal else "US Stocks / ETFs")
                qty = _float(row.get("qty"))
                avg = _float(row.get("avg_entry_price"))
                current = _float(row.get("current_price"), avg)
                market_value = abs(_float(row.get("market_value"), qty * current))
                unrealized = _float(row.get("unrealized_pl"))
                positions.append(
                    {
                        "pillar": pillar,
                        "broker": "Alpaca Paper",
                        "asset_class": asset_class or "us_equity",
                        "symbol": symbol,
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
                metrics["equity_exposure"] += 0.0 if is_crypto or is_metal else market_value
                metrics["crypto_exposure"] += market_value if is_crypto else 0.0
                metrics["metals_exposure"] += market_value if is_metal else 0.0
                pillar_status[pillar]["positions"] += 1
                pillar_status[pillar]["unrealized_pnl"] += unrealized
            for pillar in ("US Stocks / ETFs", "Crypto", "Metals / Commodities"):
                pillar_status[pillar]["state"] = "TRADING" if pillar_status[pillar]["positions"] else "FLAT"
        except Exception as exc:
            errors.append(f"Alpaca live read failed: {exc}")
    else:
        errors.append("Alpaca Streamlit secrets are not configured")

    oanda_token = _secret("OANDA_PRACTICE_TOKEN")
    oanda_account = _secret("OANDA_PRACTICE_ACCOUNT_ID")
    oanda_base = require_oanda_practice_url(
        _secret("OANDA_PRACTICE_BASE_URL") or "https://api-fxpractice.oanda.com"
    )
    if oanda_token and oanda_account:
        try:
            req = Request(
                f"{oanda_base.rstrip('/')}/v3/accounts/{oanda_account}/openPositions",
                headers={"Authorization": f"Bearer {oanda_token}", "Accept": "application/json"},
            )
            with urlopen(req, timeout=10) as r:
                payload = json.load(r)
            rows = payload.get("positions", []) if isinstance(payload, dict) else []
            pillar_status["Forex"]["connected"] = True
            pillar_status["Forex"]["positions"] = len(rows)
            pillar_status["Forex"]["state"] = "TRADING" if rows else "FLAT"
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
                        "pillar": "Forex",
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
        except Exception as exc:
            errors.append(f"OANDA live read failed: {exc}")
    else:
        errors.append("OANDA Streamlit secrets are not configured")

    return positions, metrics, pillar_status, errors


def _status_badge(label: str, value: str, kind: str = "neutral") -> str:
    return f"<div class='badge {kind}'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"


def _pillar_card(name: str, data: dict[str, object]) -> str:
    color = str(data.get("accent") or "blue")
    connection = str(data.get("connection") or "DEFERRED")
    status = str(data.get("status") or "HOLDING CASH")
    scanner = str(data.get("scanner") or "DEFERRED")
    return f"""
    <div class="pillar pillar-{color}">
      <div class="pillar-top">
        <div>
          <div class="pillar-name">{escape(name)}</div>
          <div class="pillar-sub">{escape(str(data.get('broker') or '—'))}</div>
        </div>
        <div class="pill {connection.lower().replace(' ', '-')}">{escape(connection)}</div>
      </div>
      <div class="pillar-state">{escape(status)}</div>
      <div class="pillar-grid">
        <div><span>Cap</span><strong>{_money(data.get('cap'))}</strong></div>
        <div><span>Deployed</span><strong>{_money(data.get('deployed'))}</strong></div>
        <div><span>Available</span><strong>{_money(data.get('available'))}</strong></div>
        <div><span>Realized P&L</span><strong>{_money(data.get('realized_pnl'))}</strong></div>
        <div><span>Unrealized P&L</span><strong>{_money(data.get('unrealized_pnl'))}</strong></div>
        <div><span>Positions</span><strong>{int(_float(data.get('positions')))}</strong></div>
        <div><span>Trades</span><strong>{int(_float(data.get('completed_trades')))}</strong></div>
        <div><span>Win Rate</span><strong>{escape(str(data.get('win_rate') or '—'))}</strong></div>
      </div>
      <div class="pillar-foot">
        <div><span>Scanner</span><strong>{escape(scanner)}</strong></div>
        <div><span>Last Scan</span><strong>{escape(str(data.get('last_scan') or 'DEFERRED'))}</strong></div>
        <div><span>Last Decision</span><strong>{escape(str(data.get('last_decision') or 'DEFERRED'))}</strong></div>
      </div>
    </div>
    """


def _position_row(position: dict[str, object]) -> str:
    protection = str(position.get("crypto_protection_state") or position.get("protection_state") or "—")
    lifecycle = str(position.get("crypto_lifecycle_state") or position.get("lifecycle_state") or "—")
    recon = str(position.get("crypto_reconciliation_status") or position.get("reconciliation_status") or "—")
    stop = position.get("crypto_stop_price") if position.get("crypto_stop_price") is not None else position.get("stop_price")
    return (
        "<tr>"
        f"<td>{escape(str(position.get('pillar') or '—'))}</td>"
        f"<td>{escape(str(position.get('broker') or '—'))}</td>"
        f"<td>{escape(str(position.get('symbol') or '—'))}</td>"
        f"<td>{escape(str(position.get('quantity') or '—'))}</td>"
        f"<td>{_money(position.get('average_price'))}</td>"
        f"<td>{_money(position.get('current_price'))}</td>"
        f"<td>{_money(position.get('market_value'))}</td>"
        f"<td>{_money(position.get('unrealized_pnl'))}</td>"
        f"<td>{_pct(position.get('unrealized_pct'))}</td>"
        f"<td>{_money(stop)}</td>"
        f"<td>{escape(str(position.get('target_price') or '—'))}</td>"
        f"<td>{escape(protection)}</td>"
        f"<td>{escape(str(position.get('manifest_id') or '—'))}</td>"
        f"<td>{escape(lifecycle)}</td>"
        f"<td>{escape(recon)}</td>"
        "</tr>"
    )


def _trade_row(row: dict[str, object]) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(row.get('timestamp') or row.get('closed_at') or '—'))}</td>"
        f"<td>{escape(str(row.get('pillar') or '—'))}</td>"
        f"<td>{escape(str(row.get('symbol') or row.get('instrument') or '—'))}</td>"
        f"<td>{_money(row.get('entry_price') or row.get('average_entry') or row.get('average_price'))}</td>"
        f"<td>{_money(row.get('exit_price') or row.get('price'))}</td>"
        f"<td>{_money(row.get('realized_pnl'))}</td>"
        f"<td>{_pct(row.get('realized_return') or row.get('return_pct'))}</td>"
        f"<td>{escape(str(row.get('fees_costs') or row.get('fees') or '—'))}</td>"
        f"<td>{escape(str(row.get('exit_reason') or row.get('reason') or '—'))}</td>"
        f"<td>{escape(str(row.get('model_version') or row.get('strategy_model') or '—'))}</td>"
        "</tr>"
    )


def _decision_row(row: dict[str, object]) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(row.get('time') or row.get('timestamp') or '—'))}</td>"
        f"<td>{escape(str(row.get('pillar') or '—'))}</td>"
        f"<td>{escape(str(row.get('symbol') or '—'))}</td>"
        f"<td>{escape(str(row.get('decision') or row.get('status') or '—'))}</td>"
        f"<td>{escape(str(row.get('confidence') or row.get('score') or '—'))}</td>"
        f"<td>{_money(row.get('notional') or row.get('proposed_notional'))}</td>"
        f"<td>{_money(row.get('risk') or row.get('risk_dollars'))}</td>"
        f"<td>{_money(row.get('stop'))}</td>"
        f"<td>{_money(row.get('target'))}</td>"
        f"<td>{escape(str(row.get('result') or row.get('reason') or '—'))}</td>"
        "</tr>"
    )


def render_dashboard() -> None:
    data = load_snapshot() or {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    cash = data.get("cash_dashboard") if isinstance(data.get("cash_dashboard"), dict) else {}
    learning = data.get("learning") if isinstance(data.get("learning"), dict) else {}
    targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
    positions = data.get("positions") if isinstance(data.get("positions"), list) else []
    activity = data.get("activity") if isinstance(data.get("activity"), list) else []
    unresolved = data.get("unresolved_manifests") if isinstance(data.get("unresolved_manifests"), list) else []
    pillar_performance = data.get("pillar_performance") if isinstance(data.get("pillar_performance"), dict) else {}
    live_positions, live_metrics, live_pillar_status, live_errors = fetch_live_broker_data()
    pillar_state = _pillars_from_snapshot(data)

    if live_positions:
        live_by_symbol = {str(row.get("symbol") or "").upper(): row for row in live_positions}
        for row in positions:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            live_row = live_by_symbol.get(symbol)
            if live_row:
                row.update(live_row)

    if live_pillar_status:
        for pillar_name, live_state in live_pillar_status.items():
            if pillar_name in pillar_state:
                pillar_state[pillar_name]["connection"] = "CONNECTED" if live_state.get("connected") else "DEFERRED"
                pillar_state[pillar_name]["status"] = live_state.get("state") or pillar_state[pillar_name]["status"]
                if pillar_name in {"US Stocks / ETFs", "Crypto", "Metals / Commodities", "Forex"}:
                    pillar_state[pillar_name]["positions"] = live_state.get("positions", pillar_state[pillar_name]["positions"])
                    if live_state.get("positions"):
                        pillar_state[pillar_name]["status"] = "TRADING"
                    elif pillar_state[pillar_name]["status"] == "HOLDING CASH":
                        pillar_state[pillar_name]["status"] = "FLAT"

    runtime_health = runtime_status_labels(runtime)
    current_utc = datetime.now(UTC).isoformat()
    heartbeat = runtime.get("last_heartbeat_at")
    last_cycle = runtime.get("last_cycle_finished_at") or runtime.get("last_cycle_started_at")
    runtime_age = _age_label(heartbeat)
    cycle_age = _age_label(last_cycle)
    learning_status = str(learning.get("stats", {}).get("sample_status") or "COLLECTING EVIDENCE").upper()
    autonomous_state = runtime_health["autonomous_paper_trading"]
    five_pillar_state = "RUNNING" if runtime.get("healthy") and runtime.get("execution_state") == "armed_paper" else ("READY" if runtime.get("healthy") else "FAIL-CLOSED")
    live_trading_state = "DISABLED"

    original_capital = _float(cash.get("original_capital"), TOTAL_BASE_CAPITAL)
    deployed = _float(cash.get("capital_deployed"))
    available_cash = _float(cash.get("available_cash"))
    protected_cash = _float(cash.get("protected_cash_reserve"))
    net_cash = _float(cash.get("net_trading_cash_generated"))
    unrealized = _float(cash.get("unrealized_pnl"))
    total_equity = _float(cash.get("total_portfolio_equity"), original_capital + net_cash + unrealized)
    daily_realized = _float(cash.get("daily_realized_return"))
    daily_unrealized = _float(cash.get("daily_unrealized_return"))
    cumulative_realized = _float(cash.get("cumulative_realized_return"))
    generated_cash_ratio = _float(cash.get("generated_cash_ratio"))
    dist_low = _float(targets.get("stretch_daily_low_pct"), 0.20) - daily_realized
    dist_high = _float(targets.get("stretch_daily_high_pct"), 0.40) - daily_realized

    st.markdown(
        """
        <style>
        :root {
            --bg: #07111f;
            --panel: rgba(10, 18, 33, 0.88);
            --panel-2: rgba(17, 26, 45, 0.96);
            --line: rgba(154, 176, 213, 0.18);
            --gold: #d7b56d;
            --gold-soft: rgba(215, 181, 109, 0.18);
            --text: #ecf2fb;
            --muted: #9aa9c1;
            --blue: #5fa8ff;
            --green: #4dd4a7;
            --purple: #b08cff;
            --orange: #ffb570;
            --teal: #56d1d8;
        }
        .stApp { background: radial-gradient(circle at top, #12233e 0, #07111f 35%, #050b15 100%); color: var(--text); }
        .stAppViewContainer { background: transparent; }
        .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1480px; }
        [data-testid="stHeader"] { background: rgba(5,11,21,0.86); }
        [data-testid="stSidebar"] { background: linear-gradient(180deg, rgba(8,15,28,0.98), rgba(10,18,33,0.94)); border-right: 1px solid var(--line); }
        [data-testid="stMetric"], .panel, .pillar, .table-panel, .brand-box {
            background: linear-gradient(180deg, rgba(17,26,45,0.98), rgba(10,18,33,0.95));
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: 0 16px 40px rgba(0,0,0,0.24);
        }
        [data-testid="stMetric"] { padding: .2rem .35rem; }
        [data-testid="stMetricLabel"] { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; }
        [data-testid="stMetricValue"] { color: var(--text); font-size: 1.35rem; font-weight: 700; }
        h1, h2, h3, h4 { color: var(--text); letter-spacing: .04em; }
        .hero-title { font-size: clamp(1.5rem, 2.8vw, 2.6rem); font-weight: 800; margin: 0; }
        .hero-title { font-size: clamp(1.55rem, 2.8vw, 2.7rem); font-weight: 800; margin: 0; max-width: 28ch; line-height: 1.08; }
        .hero-sub { color: var(--muted); margin-top: .35rem; font-size: .96rem; line-height: 1.55; max-width: 54ch; }
        .brand-box { padding: 1.1rem 1rem; margin-bottom: 1rem; }
        .brand-mark { display:flex; align-items:center; justify-content:center; width: 3rem; height: 3rem; border-radius: 16px; border:1px solid var(--gold); color: var(--gold); font-weight:800; margin-bottom:.75rem; background: rgba(215,181,109,0.06); }
        .brand-name { font-size: 1rem; font-weight: 800; text-transform: uppercase; letter-spacing: .14em; }
        .brand-sub, .brand-footer { color: var(--muted); font-size: .83rem; margin-top: .25rem; }
        .sidebar-nav { margin-top: 1rem; display: grid; gap: .45rem; }
        .nav-chip { padding: .55rem .7rem; border-radius: 999px; border:1px solid var(--line); color: var(--text); background: rgba(255,255,255,0.02); font-size: .86rem; }
        .status-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap:.75rem; margin: .25rem 0 1rem; }
        .status-card { padding: .95rem 1rem; }
        .status-label { color: var(--muted); font-size: .68rem; text-transform: uppercase; letter-spacing: .14em; }
        .status-value { margin-top:.25rem; font-size: 1.03rem; font-weight: 800; }
        .status-healthy { color: #72e08a; }
        .status-faulted { color: #ff7c7c; }
        .status-disarmed { color: #c8d6ef; }
        .status-armed { color: #77d8ff; }
        .status-disabled { color: #8f9bb3; }
        .badge { display:flex; justify-content:space-between; align-items:center; gap:.8rem; padding:.48rem .72rem; border-radius:999px; border:1px solid var(--line); background: rgba(255,255,255,0.03); font-size:.78rem; text-transform: uppercase; letter-spacing:.09em; }
        .badge strong { font-size:.84rem; }
        .pill { padding: .34rem .55rem; border-radius: 999px; border:1px solid var(--line); font-size:.72rem; text-transform: uppercase; letter-spacing:.12em; }
        .good { color: #74e29d; }
        .warn { color: #ffd36b; }
        .bad { color: #ff7a7a; }
        .section-title { margin: 1.4rem 0 .65rem; font-size: 1rem; text-transform: uppercase; letter-spacing: .18em; color: var(--gold); }
        .pillar-wrap { display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:.75rem; }
        .pillar { padding: .95rem; min-height: 260px; position:relative; overflow:hidden; }
        .pillar::before { content:''; position:absolute; inset:0 auto auto 0; width:100%; height:3px; background: var(--accent, var(--gold)); opacity:.88; }
        .pillar-blue { --accent: var(--blue); }
        .pillar-green { --accent: var(--green); }
        .pillar-purple { --accent: var(--purple); }
        .pillar-gold { --accent: var(--orange); }
        .pillar-teal { --accent: var(--teal); }
        .pillar-top { display:flex; justify-content:space-between; gap:.6rem; align-items:flex-start; margin-bottom:.7rem; }
        .pillar-name { font-size: .92rem; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
        .pillar-sub { color: var(--muted); font-size: .75rem; margin-top:.2rem; }
        .pillar-state { font-size: 1.05rem; font-weight: 800; margin: .4rem 0 .7rem; color: var(--text); }
        .pillar-grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:.55rem .7rem; }
        .pillar-grid span, .pillar-foot span { display:block; color: var(--muted); font-size:.67rem; text-transform:uppercase; letter-spacing:.14em; }
        .pillar-grid strong, .pillar-foot strong { display:block; margin-top:.15rem; font-size:.88rem; }
        .pillar-foot { display:grid; gap:.45rem; margin-top:.7rem; }
        .table-panel { padding: .85rem; overflow-x:auto; }
        table { width:100%; border-collapse: collapse; min-width: 980px; }
        th, td { border-bottom:1px solid var(--line); padding: .6rem .5rem; font-size:.84rem; vertical-align: top; }
        th { text-transform: uppercase; letter-spacing:.12em; color: var(--muted); font-size:.67rem; }
        .small-note { color: var(--muted); font-size: .78rem; line-height: 1.6; }
        .alloc-grid { display:grid; grid-template-columns: repeat(5, 1fr); gap:.6rem; }
        .alloc { padding:.8rem; border-radius:16px; border:1px solid var(--line); background: rgba(255,255,255,0.03); text-align:center; }
        .alloc .k { text-transform:uppercase; letter-spacing:.12em; font-size:.66rem; color: var(--muted); }
        .alloc .v { margin-top:.35rem; font-size:1rem; font-weight:800; }
        .progress { width:100%; height:8px; border-radius:999px; background: rgba(255,255,255,0.06); overflow:hidden; margin-top:.4rem; }
        .progress > div { height:100%; background: linear-gradient(90deg, var(--gold), #88d7ff); }
        @media (max-width: 1100px) { .pillar-wrap, .alloc-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
        @media (max-width: 768px) {
            .pillar-wrap, .alloc-grid, .status-grid { grid-template-columns: 1fr; }
            .block-container { padding-left: .9rem; padding-right: .9rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        f"""
        <div class="brand-box">
          <div class="brand-mark">CH</div>
          <div class="brand-name">Chris Haake<br>Capital Systems</div>
          <div class="brand-sub">FIVE-PILLAR AUTONOMOUS SYSTEM</div>
          <div class="brand-sub">Christopher J. Haake</div>
          <div class="brand-footer">Research. Discipline. Execution.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        """
        <div class="sidebar-nav">
          <div class="nav-chip">OVERVIEW</div>
          <div class="nav-chip">PILLARS</div>
          <div class="nav-chip">POSITIONS</div>
          <div class="nav-chip">TRADES</div>
          <div class="nav-chip">LEARNING</div>
          <div class="nav-chip">PERFORMANCE</div>
          <div class="nav-chip">RISK &amp; HEALTH</div>
          <div class="nav-chip">EXECUTION LOG</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="hero-title">FIVE-PILLAR AUTONOMOUS TRADING COMMAND CENTER</div>
        <div class="hero-sub">Research · Execution · Learning · Capital Discipline</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("CHRIS HAAKE CAPITAL SYSTEMS")

    status_labels = runtime_status_labels(runtime)
    runtime_health = status_labels["runtime_health"]
    autonomous_state = status_labels["autonomous_paper_trading"]
    live_trading_state = status_labels["live_trading"]
    five_pillar_state = "RUNNING" if runtime.get("healthy") and runtime.get("execution_state") == "armed_paper" else (
        "READY" if runtime.get("healthy") else "FAIL-CLOSED"
    )
    learning_status = str(learning.get("stats", {}).get("sample_status") or "COLLECTING EVIDENCE").upper()
    if learning_status not in {"ACTIVE", "COLLECTING EVIDENCE", "DEGRADED"}:
        learning_status = "COLLECTING EVIDENCE"
    heartbeat = runtime.get("last_heartbeat_at")
    last_cycle = runtime.get("last_cycle_finished_at") or runtime.get("last_cycle_started_at")

    st.markdown(
        f"""
        <div class="status-grid">
          <div class="status-card panel">
            <div class="status-label">System Status</div>
            <div class="status-value {'status-healthy' if runtime_health == 'Healthy' else 'status-faulted'}">{escape(runtime_health)}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Autonomous PAPER</div>
            <div class="status-value {'status-armed' if 'ARMED' in autonomous_state else 'status-disarmed'}">{escape(autonomous_state)}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Live Trading</div>
            <div class="status-value status-disabled">{escape(live_trading_state)}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Five-Pillar Status</div>
            <div class="status-value">{escape(five_pillar_state)}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Learning Engine</div>
            <div class="status-value">{escape(learning_status)}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Last Heartbeat</div>
            <div class="status-value">{escape(_age_label(heartbeat))}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Last Cycle</div>
            <div class="status-value">{escape(_age_label(last_cycle))}</div>
          </div>
          <div class="status-card panel">
            <div class="status-label">Current UTC Time</div>
            <div class="status-value">{escape(datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'))} UTC</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Five Pillars</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='pillar-wrap'>" + "".join(_pillar_card(name, data) for name, data in pillar_state.items()) + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Capital & Cash Command Center</div>", unsafe_allow_html=True)
    cash_cols = st.columns(4)
    cash_cols[0].metric("Starting Strategy Capital", _money(original_capital))
    cash_cols[1].metric("Capital Deployed", _money(deployed))
    cash_cols[2].metric("Available Cash", _money(available_cash))
    cash_cols[3].metric("Protected / Harvested Cash", _money(protected_cash))
    cash_cols2 = st.columns(4)
    cash_cols2[0].metric("Daily Net Trading Cash", _money(net_cash))
    cash_cols2[1].metric("Cumulative Net Trading Cash", _money(net_cash))
    cash_cols2[2].metric("Unrealized P&L", _money(unrealized))
    cash_cols2[3].metric("Total Strategy Equity", _money(total_equity))
    cash_cols3 = st.columns(4)
    cash_cols3[0].metric("Daily Realized Return", _pct(daily_realized))
    cash_cols3[1].metric("Daily Unrealized Return", _pct(daily_unrealized))
    cash_cols3[2].metric("Cumulative Realized Return", _pct(cumulative_realized))
    cash_cols3[3].metric("Generated Cash Ratio", _pct(generated_cash_ratio))

    st.markdown("<div class='section-title'>Performance & Return Targets</div>", unsafe_allow_html=True)
    target_cols = st.columns(2)
    target_cols[0].markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="status-label">Operating Benchmark — reporting only</div>
          <div class="status-value">$20–$305 Daily Realized Cash</div>
          <div class="small-note">Benchmarks do not force trades. Cash/no-trade is valid.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    target_cols[1].markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="status-label">Stretch Benchmark — reporting only</div>
          <div class="status-value">20%–40% Daily Return</div>
          <div class="small-note">Current realized return: {escape(_pct(daily_realized))} · current unrealized return: {escape(_pct(daily_unrealized))}</div>
          <div class="small-note">Distance to 20%: {escape(_pct(dist_low))} · Distance to 40%: {escape(_pct(dist_high))}</div>
          <div class="progress"><div style="width:{max(0.0, min(100.0, abs(daily_realized) / 0.40 * 100.0)):.1f}%"></div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    allocation_rows = "".join(
        f"<div class='alloc'><div class='k'>{escape(name)}</div><div class='v'>{_money(PILLAR_BASE_CAPITAL)}<br><span style='color:var(--muted);font-size:.78rem'>20%</span></div></div>"
        for name, _, _ in PILLARS
    )
    st.markdown(
        f"""
        <div class='section-title'>Capital Allocation</div>
        <div class='alloc-grid'>{allocation_rows}</div>
        <div class='small-note' style='margin-top:.45rem'>Caps are hard internal limits and never expand from broker buying power or Saxo virtual equity.</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Open Positions</div>", unsafe_allow_html=True)
    if positions:
        rows_html = "".join(_position_row(row) for row in positions)
        st.markdown(
            f"""
            <div class="table-panel">
            <table>
              <thead>
                <tr>
                  <th>Pillar</th><th>Broker</th><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th>
                  <th>Market Value</th><th>Unrealized P&L</th><th>Return %</th><th>Stop</th><th>Target</th>
                  <th>Protection</th><th>Manifest</th><th>Lifecycle</th><th>Reconciliation</th>
                </tr>
              </thead><tbody>{rows_html}</tbody></table></div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No open managed positions were found in the current snapshot.")

    st.markdown("<div class='section-title'>Learning Intelligence</div>", unsafe_allow_html=True)
    learning_meta = learning.get("model_state") if isinstance(learning.get("model_state"), dict) else {}
    learning_stats = learning.get("stats") if isinstance(learning.get("stats"), dict) else {}
    learning_params = learning.get("parameters") if isinstance(learning.get("parameters"), dict) else {}
    lp1, lp2, lp3, lp4 = st.columns(4)
    lp1.metric("Baseline Model", str(learning_meta.get("baseline_version") or "five_pillar_baseline_v1"))
    lp2.metric("Challenger", str(learning_meta.get("active_version") or "challenger_candidate_v1"))
    lp3.metric("Completed Trades", str(learning_stats.get("completed_trades") or 0))
    lp4.metric("Learning Status", str(learning_stats.get("sample_status") or "COLLECTING EVIDENCE"))
    st.markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="small-note">Current bounded parameters: <code>{escape(json.dumps(learning_params, sort_keys=True))}</code></div>
          <div class="small-note">Recent parameter changes, promotion eligibility, promotion/rollback history, and model cash contribution are read from the durable learning snapshot when available.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Execution & System Health</div>", unsafe_allow_html=True)
    exec_cols = st.columns(4)
    exec_cols[0].metric("Unresolved Manifests", str(int(_float(runtime.get("unresolved_manifest_count"), 0.0))))
    exec_cols[1].metric("Broker Requests", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("requests"), 0.0))))
    exec_cols[2].metric("Retries", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("retries"), 0.0))))
    exec_cols[3].metric("429 Events", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("rate_limited"), 0.0))))
    if live_errors:
        st.warning(" · ".join(live_errors))

    recent_activity = activity[:12]
    if recent_activity:
        rows_html = "".join(
            f"<tr><td>{escape(str(row.get('time') or '—'))}</td><td>{escape(str(row.get('event') or '—'))}</td><td>{escape(str(row.get('message') or '—'))}</td></tr>"
            for row in recent_activity
        )
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Time UTC</th><th>Event</th><th>Message</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if unresolved:
        unresolved_rows = "".join(
            f"<tr><td>{escape(str(row.get('created_at') or '—'))}</td><td>{escape(str(row.get('canonical_symbol') or '—'))}</td><td>{escape(str(row.get('broker_order_id') or '—'))}</td><td>{escape(str(row.get('lifecycle_state') or '—'))}</td></tr>"
            for row in unresolved[:20]
        )
        st.markdown(
            f"""
            <div class="section-title">Unresolved Manifests</div>
            <div class="table-panel">
              <table>
                <thead><tr><th>Created</th><th>Symbol</th><th>Broker Order ID</th><th>Lifecycle</th></tr></thead>
                <tbody>{unresolved_rows}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="small-note" style="margin-top:1rem">
          Streamlit Cloud install note: the app expects the local package to be installed, so the `src/` imports resolve cleanly without a private runtime checkout.
          Secret names expected on Cloud: ALPACA_PAPER_API_KEY, ALPACA_PAPER_SECRET_KEY, ALPACA_PAPER_BASE_URL, OANDA_PRACTICE_TOKEN, OANDA_PRACTICE_ACCOUNT_ID, OANDA_PRACTICE_BASE_URL, and SAXO_* SIM-only values when applicable.
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    render_dashboard()


if __name__ == "__main__":
    main()
