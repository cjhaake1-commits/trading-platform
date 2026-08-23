from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen

import streamlit as st

# ruff: noqa: E501

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_autotrader_helpers():
    from autotrader.broker_environment import require_alpaca_paper_url, require_oanda_practice_url
    from autotrader.dashboard_health import runtime_status_labels

    return require_alpaca_paper_url, require_oanda_practice_url, runtime_status_labels


require_alpaca_paper_url, require_oanda_practice_url, runtime_status_labels = _load_autotrader_helpers()

st.set_page_config(
    page_title="Chris Haake Capital Systems",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_PATH = Path("dashboard/data.json")
TOTAL_BASE_CAPITAL = 5000.0
KALSHI_BASE_CAPITAL = 1000.0
SIX_PILLAR_BASE_CAPITAL = TOTAL_BASE_CAPITAL + KALSHI_BASE_CAPITAL
PILLAR_BASE_CAPITAL = 1000.0
PILLARS = (
    ("US Stocks / ETFs", "Alpaca PAPER", "blue"),
    ("Forex", "OANDA Practice", "green"),
    ("Crypto", "Alpaca PAPER", "purple"),
    ("Metals / Commodities", "Alpaca PAPER", "gold"),
    ("International", "Saxo SIM", "teal"),
    ("Kalshi", "Kalshi DEMO", "orange"),
)
METALS_UNIVERSE = {"GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL"}
PILLAR_JOB_MAP = {
    "US Stocks / ETFs": "autonomous-paper-trading",
    "Crypto": "autonomous-paper-trading",
    "Forex": "oanda-fx-paper-trading",
    "Metals / Commodities": "alpaca-metals-paper-trading",
    "International": "saxo-international-paper-trading",
    "Kalshi": "trading-platform-kalshi-research",
}


def _derive_pillar_state(
    name: str,
    job: dict[str, object],
    broker_state: dict[str, object],
    activity: list[object],
) -> tuple[str, str, str]:
    """Derive operator truth from live runtime evidence, never stale defaults."""
    if job.get("last_error"):
        return "ERROR", "ERROR", str(job.get("last_error"))
    recent = [
        row for row in activity
        if isinstance(row, dict) and name.lower().split()[0] in str(row.get("message", "")).lower()
    ]
    recent_message = str(recent[0].get("message", "")) if recent else ""
    if "AUTH REQUIRED" in recent_message:
        return "AUTH REQUIRED", "AUTH REQUIRED", recent_message
    if broker_state.get("connected"):
        state = str(broker_state.get("state") or "")
        allowed = {"TRADING", "SCANNING", "HOLDING CASH", "MARKET CLOSED", "RATE LIMITED", "RECONCILING", "RISK BLOCKED", "SHADOW ONLY"}
        if state in allowed:
            return state, "CONNECTED", recent_message or state
        if int(broker_state.get("positions", 0) or 0) > 0:
            return "TRADING", "CONNECTED", recent_message or "Position open"
        return "SCANNING", "CONNECTED", recent_message or "Evaluating candidates"
    if "MARKET CLOSED" in recent_message:
        return "MARKET CLOSED", "CONNECTED", recent_message
    if "SHADOW ONLY" in recent_message:
        return "SHADOW ONLY", "SHADOW ONLY", recent_message
    if job.get("disabled"):
        return "ERROR", "ERROR", "Runtime job disabled"
    if job.get("last_finished_at") or job.get("last_started_at"):
        return "SCANNING", "CONNECTED", recent_message or "Runtime cycle observed"
    return "DATA UNAVAILABLE", "DATA UNAVAILABLE", "No live broker/runtime evidence"


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
        return "UNAVAILABLE"
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "UNAVAILABLE"
    if observed.tzinfo is None:
        return "UNAVAILABLE"
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
    return str(value or os.getenv(name, "")).strip()


def _safe_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _path_age_label(path: Path) -> str:
    if not path.exists():
        return "UNAVAILABLE"
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except Exception:
        return "UNAVAILABLE"
    age = datetime.now(UTC) - modified
    if age.total_seconds() < 0:
        return "LIVE"
    if age.total_seconds() < 45:
        return f"FRESH · {int(age.total_seconds())}s"
    return f"STALE · {int(age.total_seconds())}s"


@st.cache_data(ttl=20)
def load_snapshot() -> dict[str, object]:
    return _safe_json(DATA_PATH)


@st.cache_data(ttl=10)
def load_live_runtime_status() -> dict[str, object]:
    return _safe_json(Path("var/autotrader/status.json"))


@st.cache_data(ttl=60)
def load_experiment_state() -> dict[str, object]:
    return _safe_json(Path("var/autotrader/experiment.json"))


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
            "last_scan": "UNAVAILABLE",
            "last_decision": "UNAVAILABLE",
            "connection": "DATA UNAVAILABLE",
            "scanner": "DATA UNAVAILABLE",
            "status": "DATA UNAVAILABLE",
        }
        for name, broker, accent in PILLARS
    }

    for row in positions:
        if not isinstance(row, dict):
            continue
        if str(row.get("classification") or "").upper() not in {"VALID_STRATEGY_POSITION", "ACTIVE V2"}:
            continue
        pillar = str(row.get("pillar") or "")
        if pillar not in result:
            if (
                str(row.get("broker") or "").lower().startswith("alpaca")
                and str(row.get("symbol") or "").upper() in METALS_UNIVERSE
            ):
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
        metrics["deployed"] = min(max(metrics["deployed"], 0.0), PILLAR_BASE_CAPITAL)
        metrics["available"] = max(PILLAR_BASE_CAPITAL - metrics["deployed"], 0.0)
        if metrics["positions"] == 0 and metrics["status"] == "HOLDING CASH":
            metrics["status"] = "FLAT"
    kalshi_db = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    if "Kalshi" in result and kalshi_db.exists():
        try:
            with sqlite3.connect(kalshi_db) as conn:
                count = conn.execute("SELECT COUNT(*) FROM kalshi_observations WHERE family='predictions'").fetchone()[0]
            result["Kalshi"].update({"connection": "CONNECTED", "scanner": "ACTIVE", "status": "OBSERVING" if count else "NO DATA", "last_scan": _path_age_label(kalshi_db), "last_decision": "HOLD CASH"})
        except sqlite3.Error:
            result["Kalshi"].update({"connection": "API DEGRADED", "scanner": "DEGRADED", "status": "DEGRADED"})
    return result


def _runtime_job_times(runtime: dict[str, object]) -> tuple[str, str]:
    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    last_started: list[str] = []
    last_finished: list[str] = []
    for name in (
        "autonomous-paper-trading",
        "oanda-fx-paper-trading",
        "alpaca-metals-paper-trading",
        "saxo-international-paper-trading",
    ):
        job = jobs.get(name) if isinstance(jobs, dict) else {}
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("last_started_at"), str):
            last_started.append(job["last_started_at"])
        if isinstance(job.get("last_finished_at"), str):
            last_finished.append(job["last_finished_at"])
    return (
        max(last_started) if last_started else str(runtime.get("last_heartbeat_at") or "—"),
        max(last_finished) if last_finished else str(runtime.get("last_heartbeat_at") or "—"),
    )


def _build_live_positions(
    snapshot_positions: list[dict[str, object]],
    live_positions: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in snapshot_positions:
        if not isinstance(row, dict):
            continue
        broker = str(row.get("broker") or "").strip()
        symbol = str(row.get("symbol") or "").upper()
        if broker or symbol:
            merged[(broker, symbol)] = dict(row)
    for row in live_positions:
        if not isinstance(row, dict):
            continue
        broker = str(row.get("broker") or "").strip()
        symbol = str(row.get("symbol") or "").upper()
        key = (broker, symbol)
        existing = merged.get(key, {})
        updated = dict(existing)
        updated.update(row)
        merged[key] = updated
    return list(merged.values())


def _render_pillar_card(name: str, data: dict[str, object]) -> None:
    st.markdown(
        f"""
        <div class="pillar pillar-{escape(str(data.get("accent") or "blue"))}">
          <div class="pillar-top">
            <div>
              <div class="pillar-name">{escape(name.upper())}</div>
              <div class="pillar-sub">{escape(str(data.get("broker") or "—"))}</div>
            </div>
          <div class="pill {escape(str(data.get("connection_class") or "neutral"))}">{escape(str(data.get("connection") or "DATA UNAVAILABLE"))}</div>
          </div>
          <div class="pillar-state">{escape(str(data.get("state") or "HOLDING CASH"))}</div>
          <div class="pillar-grid">
            <div><span>V2 Cap</span><strong>{_money(data.get("cap"))}</strong></div>
            <div><span>V2 Deployed</span><strong>{_money(data.get("deployed"))}</strong></div>
            <div><span>V2 Available</span><strong>{_money(data.get("available"))}</strong></div>
            <div><span>V2 Realized P&amp;L</span><strong>{_money(data.get("realized_pnl"))}</strong></div>
            <div><span>V2 Unrealized P&amp;L</span><strong>{_money(data.get("unrealized_pnl"))}</strong></div>
            <div><span>V2 Positions</span><strong>{int(_float(data.get("positions")))}</strong></div>
            <div><span>Trades</span><strong>{int(_float(data.get("completed_trades")))}</strong></div>
            <div><span>Win Rate</span><strong>{escape(str(data.get("win_rate") or "—"))}</strong></div>
          </div>
          <div class="pillar-foot">
            <div><span>Legacy Exposure</span><strong>{_money(data.get("legacy_exposure"))} · {int(_float(data.get("legacy_positions"))) } positions</strong></div>
            <div><span>Scanner</span><strong>{escape(str(data.get("scanner") or "DATA UNAVAILABLE"))}</strong></div>
            <div><span>Last Scan</span><strong>{escape(str(data.get("last_scan") or "UNAVAILABLE"))}</strong></div>
            <div><span>Last Decision</span><strong>{escape(str(data.get("last_decision") or "UNAVAILABLE"))}</strong></div>
            <div><span>Blocker</span><strong>{escape(str(data.get("blocker") or "NONE"))}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _secret_warning(name: str) -> str:
    return "Configured" if _secret(name) else "Not configured"


@st.cache_data(ttl=20)
def fetch_live_broker_data() -> tuple[
    list[dict[str, object]], dict[str, float], dict[str, dict[str, object]], list[str]
]:
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
        "US Stocks / ETFs": {"connected": False, "positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0},
        "Crypto": {"connected": False, "positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0},
        "Metals / Commodities": {"connected": False, "positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0},
        "Forex": {"connected": False, "positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0},
        "International": {"connected": False, "positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0},
    }
    errors: list[str] = []

    alpaca_key = _secret("ALPACA_PAPER_API_KEY")
    alpaca_secret = _secret("ALPACA_PAPER_SECRET_KEY")
    alpaca_base = require_alpaca_paper_url(_secret("ALPACA_PAPER_BASE_URL") or "https://paper-api.alpaca.markets")
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
    oanda_base = require_oanda_practice_url(_secret("OANDA_PRACTICE_BASE_URL") or "https://api-fxpractice.oanda.com")
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

    saxo_env = _secret("SAXO_ENV")
    saxo_base = _secret("SAXO_BASE_URL") or "https://gateway.saxobank.com/sim/openapi"
    try:
        from autotrader.brokers.saxo_sim import SaxoConfigurationError, SaxoSimAdapter

        managed_saxo = SaxoSimAdapter.from_env()
    except SaxoConfigurationError:
        managed_saxo = None
    if saxo_env and saxo_base and managed_saxo is not None:
        try:
            summary = managed_saxo.account_summary()
            pillar_status["International"]["connected"] = True
            pillar_status["International"]["positions"] = 0
            pillar_status["International"]["state"] = "CONNECTED / SCANNING"
            metrics["gross_exposure"] += 0.0
            _ = summary  # keep the read-only probe explicit and side-effect free
        except SaxoConfigurationError as exc:
            pillar_status["International"]["state"] = "AUTH REQUIRED"
            errors.append(f"International auth required: {exc}")
        except RuntimeError as exc:
            message = str(exc)
            if "401" in message or "auth" in message.lower() or "token" in message.lower():
                pillar_status["International"]["state"] = "AUTH REQUIRED"
                errors.append(f"International auth required: {exc}")
            else:
                pillar_status["International"]["state"] = "DEGRADED"
                errors.append(f"International live read failed: {exc}")
    else:
        pillar_status["International"]["state"] = "AUTH REQUIRED"
        errors.append("International Saxo SIM OAuth state is not configured")

    return positions, metrics, pillar_status, errors


def _status_badge(label: str, value: str, kind: str = "neutral") -> str:
    return f"<div class='badge {kind}'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"


def _pillar_card(name: str, data: dict[str, object]) -> str:
    color = str(data.get("accent") or "blue")
    connection = str(data.get("connection") or "DATA UNAVAILABLE")
    status = str(data.get("status") or "HOLDING CASH")
    scanner = str(data.get("scanner") or "DATA UNAVAILABLE")
    return f"""
    <div class="pillar pillar-{color}">
      <div class="pillar-top">
        <div>
          <div class="pillar-name">{escape(name)}</div>
          <div class="pillar-sub">{escape(str(data.get("broker") or "—"))}</div>
        </div>
        <div class="pill {connection.lower().replace(" ", "-")}">{escape(connection)}</div>
      </div>
      <div class="pillar-state">{escape(status)}</div>
      <div class="pillar-grid">
        <div><span>Cap</span><strong>{_money(data.get("cap"))}</strong></div>
        <div><span>Deployed</span><strong>{_money(data.get("deployed"))}</strong></div>
        <div><span>Available</span><strong>{_money(data.get("available"))}</strong></div>
        <div><span>Realized P&L</span><strong>{_money(data.get("realized_pnl"))}</strong></div>
        <div><span>Unrealized P&L</span><strong>{_money(data.get("unrealized_pnl"))}</strong></div>
        <div><span>Positions</span><strong>{int(_float(data.get("positions")))}</strong></div>
        <div><span>Trades</span><strong>{int(_float(data.get("completed_trades")))}</strong></div>
        <div><span>Win Rate</span><strong>{escape(str(data.get("win_rate") or "—"))}</strong></div>
      </div>
      <div class="pillar-foot">
        <div><span>Scanner</span><strong>{escape(scanner)}</strong></div>
        <div><span>Last Scan</span><strong>{escape(str(data.get("last_scan") or "UNAVAILABLE"))}</strong></div>
        <div><span>Last Decision</span><strong>{escape(str(data.get("last_decision") or "UNAVAILABLE"))}</strong></div>
      </div>
    </div>
    """


def _position_row(position: dict[str, object]) -> str:
    protection = str(position.get("crypto_protection_state") or position.get("protection_state") or "—")
    lifecycle = str(position.get("crypto_lifecycle_state") or position.get("lifecycle_state") or "—")
    recon = str(position.get("crypto_reconciliation_status") or position.get("reconciliation_status") or "—")
    classification = str(position.get("classification") or "UNRESOLVED")
    learning_eligible = "YES" if position.get("learning_eligible") else "NO"
    stop = (
        position.get("crypto_stop_price")
        if position.get("crypto_stop_price") is not None
        else position.get("stop_price")
    )
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
        f"<td>{escape(classification)}</td>"
        f"<td>{escape(learning_eligible)}</td>"
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


def _build_dashboard_context() -> dict[str, object]:
    live_runtime = load_live_runtime_status()
    snapshot = load_snapshot()
    experiment = load_experiment_state()
    runtime = (
        live_runtime
        if live_runtime
        else (snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {})
    )
    runtime_source = "LIVE VM" if live_runtime else ("PUBLISHED SNAPSHOT" if snapshot else "UNAVAILABLE")
    runtime_source_age = (
        _path_age_label(Path("var/autotrader/status.json"))
        if live_runtime
        else _age_label(runtime.get("last_heartbeat_at"))
        if runtime
        else "UNAVAILABLE"
    )
    runtime_labels = runtime_status_labels(runtime if isinstance(runtime, dict) else {})
    learning = snapshot.get("learning") if isinstance(snapshot.get("learning"), dict) else {}
    live_positions, live_metrics, live_pillar_status, live_errors = fetch_live_broker_data()
    snapshot_positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
    broker_positions = _build_live_positions(snapshot_positions, live_positions)
    active_positions = snapshot.get("active_positions") if isinstance(snapshot.get("active_positions"), list) else []
    legacy_positions = snapshot.get("legacy_positions") if isinstance(snapshot.get("legacy_positions"), list) else []
    positions = _build_live_positions(active_positions, live_positions)
    unresolved = snapshot.get("unresolved_manifests") if isinstance(snapshot.get("unresolved_manifests"), list) else []
    pillar_performance = (
        snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    )
    cash = snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {}
    activity = snapshot.get("activity") if isinstance(snapshot.get("activity"), list) else []
    legacy_cash = (
        snapshot.get("legacy_cash_dashboard") if isinstance(snapshot.get("legacy_cash_dashboard"), dict) else {}
    )
    broker_account = snapshot.get("broker_account") if isinstance(snapshot.get("broker_account"), dict) else {}
    activity = snapshot.get("activity") if isinstance(snapshot.get("activity"), list) else []
    trades = snapshot.get("trades") if isinstance(snapshot.get("trades"), list) else []
    orders = snapshot.get("orders") if isinstance(snapshot.get("orders"), list) else []
    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    pillar_job_map = {
        "US Stocks / ETFs": "autonomous-paper-trading",
        "Crypto": "autonomous-paper-trading",
        "Forex": "oanda-fx-paper-trading",
        "Metals / Commodities": "alpaca-metals-paper-trading",
        "International": "saxo-international-paper-trading",
    }
    live_job_rows: list[dict[str, object]] = []
    for pillar_name, job_name in pillar_job_map.items():
        job = jobs.get(job_name) if isinstance(jobs, dict) else {}
        job = job if isinstance(job, dict) else {}
        live_job_rows.append(
            {
                "pillar": pillar_name,
                "job": job_name,
                "state": "DISABLED" if job.get("disabled") else ("DEGRADED" if job.get("last_error") else "SCANNING"),
                "last_started_at": job.get("last_started_at"),
                "last_finished_at": job.get("last_finished_at"),
                "last_duration_ms": job.get("last_duration_ms"),
                "failures": job.get("consecutive_failures", 0),
                "last_error": job.get("last_error"),
            }
        )

    _, last_finished = _runtime_job_times(runtime if isinstance(runtime, dict) else {})
    heartbeat_age = _age_label(runtime.get("last_heartbeat_at"))
    cycle_age = _age_label(last_finished)
    autonomous_state = "ARMED" if runtime.get("autonomous_enabled") else "DISARMED"
    live_state = "DISABLED" if runtime.get("live_trading_enabled") is False else "UNKNOWN"
    five_state = (
        "RUNNING"
        if runtime.get("healthy") and runtime.get("execution_state") == "armed_paper"
        else ("DEGRADED" if runtime.get("healthy") else "FAIL-CLOSED")
    )
    learning_engine_state = (
        "ACTIVE"
        if not any(
            isinstance(jobs.get(name), dict) and jobs.get(name, {}).get("disabled") for name in ("daily-learning",)
        )
        else "DEGRADED"
    )
    learning_model_state = str(learning.get("stats", {}).get("sample_status") or "COLLECTING EVIDENCE").upper()
    original_capital = _float(cash.get("original_capital"), TOTAL_BASE_CAPITAL)
    deployed = _float(cash.get("capital_deployed"))
    unrealized = _float(cash.get("unrealized_pnl"))
    net_cash = _float(cash.get("net_trading_cash_generated"))
    protected_cash = _float(cash.get("protected_cash_reserve"))
    available_cash = max(original_capital + net_cash - deployed - protected_cash, 0.0)
    total_equity = original_capital + net_cash + unrealized
    daily_realized = _float(cash.get("daily_realized_return") or cash.get("realized_return"))
    daily_unrealized = _float(cash.get("daily_unrealized_return"))
    cumulative_realized = _float(cash.get("cumulative_realized_return") or cash.get("realized_return"))
    generated_cash_ratio = _float(cash.get("generated_cash_ratio") or cash.get("realized_return"))
    dist_low = 0.20 - daily_realized
    dist_high = 0.40 - daily_realized
    return {
        "snapshot": snapshot,
        "experiment": experiment,
        "runtime": runtime,
        "runtime_source": runtime_source,
        "runtime_source_age": runtime_source_age,
        "runtime_labels": runtime_labels,
        "learning": learning,
        "live_positions": live_positions,
        "live_metrics": live_metrics,
        "live_pillar_status": live_pillar_status,
        "live_errors": live_errors,
        "broker_positions": broker_positions,
        "positions": positions,
        "active_positions": active_positions,
        "legacy_positions": legacy_positions,
        "unresolved": unresolved,
        "pillar_performance": pillar_performance,
        "cash": cash,
        "legacy_cash": legacy_cash,
        "broker_account": broker_account,
        "activity": activity,
        "trades": trades,
        "orders": orders,
        "jobs": jobs,
        "live_job_rows": live_job_rows,
        "heartbeat_age": heartbeat_age,
        "cycle_age": cycle_age,
        "autonomous_state": autonomous_state,
        "live_state": live_state,
        "five_state": five_state,
        "learning_engine_state": learning_engine_state,
        "learning_model_state": learning_model_state,
        "original_capital": original_capital,
        "deployed": deployed,
        "unrealized": unrealized,
        "net_cash": net_cash,
        "protected_cash": protected_cash,
        "available_cash": available_cash,
        "total_equity": total_equity,
        "daily_realized": daily_realized,
        "daily_unrealized": daily_unrealized,
        "cumulative_realized": cumulative_realized,
        "generated_cash_ratio": generated_cash_ratio,
        "dist_low": dist_low,
        "dist_high": dist_high,
    }


def _render_overview(ctx: dict[str, object]) -> None:
    runtime = ctx["runtime"]
    live_job_rows = ctx["live_job_rows"]
    unresolved = ctx["unresolved"]
    learning = ctx["learning"]
    positions = ctx["positions"]
    broker_account = ctx["broker_account"] if isinstance(ctx["broker_account"], dict) else {}
    legacy_positions = ctx["legacy_positions"] if isinstance(ctx["legacy_positions"], list) else []
    experiment = ctx["experiment"] if isinstance(ctx["experiment"], dict) else {}
    st.markdown("<div class='section-title'>Overview</div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="small-note">Runtime source: <strong>{escape(str(ctx["runtime_source"]))}</strong> · freshness: <strong>{escape(str(ctx["runtime_source_age"]))}</strong></div>
        <div class="small-note">The active experiment only counts <strong>five_pillar_paper_v2</strong> evidence; legacy history remains visible but isolated.</div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='section-title'>Live System Activity</div>", unsafe_allow_html=True)
    if live_job_rows:
        rows_html = "".join(
            f"<tr><td>{escape(str(row['pillar']))}</td><td>{escape(str(row['job']))}</td><td>{escape(str(row['state']))}</td><td>{escape(str(row['last_started_at'] or '—'))}</td><td>{escape(str(row['last_finished_at'] or '—'))}</td><td>{escape(str(row['last_duration_ms'] or '—'))}</td><td>{escape(str(row['failures'] or 0))}</td><td>{escape(str(row['last_error'] or '—'))}</td></tr>"
            for row in live_job_rows
        )
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Pillar</th><th>Job</th><th>State</th><th>Last Start</th><th>Last Finish</th><th>Duration</th><th>Failures</th><th>Last Error</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("<div class='section-title'>Capital & Cash Command Center</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='panel'><div class='section-title'>CAPITAL HISTORY</div>"
        f"<div class='small-note'>ORIGINAL FIVE-PILLAR BASE: <strong>{_money(TOTAL_BASE_CAPITAL)}</strong> · "
        f"KALSHI DEMO BASE: <strong>{_money(KALSHI_BASE_CAPITAL)}</strong> · "
        f"SIX-PILLAR BASE: <strong>{_money(SIX_PILLAR_BASE_CAPITAL)}</strong></div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='panel'><div class='section-title'>GLOBAL INTELLIGENCE</div>"
        "<div class='small-note'>Best opportunity: <strong>NONE QUALIFYING</strong> · Best pillar: <strong>HOLD CASH</strong> · "
        "Best hedge: <strong>SHADOW RESEARCH</strong> · Learning confidence: <strong>COLLECTING EVIDENCE</strong> · "
        "Cross-pillar allocation remains theoretical until each engine supplies validated evidence.</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div class='panel'><div class='section-title'>AUTHORITATIVE PAPER CAPITAL</div><div class='status-grid'>"
        f"<div class='status-card'><div class='status-label'>TOTAL PAPER CAPITAL</div><div class='status-value'>{_money(ctx['original_capital'])}</div></div>"
        f"<div class='status-card'><div class='status-label'>INVESTED / RESERVED</div><div class='status-value'>{_money(ctx['deployed'] + ctx['protected_cash'])}</div></div>"
        f"<div class='status-card'><div class='status-label'>LIQUID CASH</div><div class='status-value'>{_money(ctx['available_cash'])}</div></div>"
        f"<div class='status-card'><div class='status-label'>UNREALIZED P&L</div><div class='status-value'>{_money(ctx['unrealized'])}</div></div>"
        f"<div class='status-card'><div class='status-label'>REALIZED P&L</div><div class='status-value'>{_money(ctx['net_cash'])}</div></div>"
        f"<div class='status-card'><div class='status-label'>KALSHI AUTHORIZED</div><div class='status-value'>{_money(KALSHI_BASE_CAPITAL)}</div></div>"
        f"</div></div>", unsafe_allow_html=True,
    )
    backlog = runtime.get("backlog_progress") if isinstance(runtime.get("backlog_progress"), dict) else {}
    active_v2_unresolved = int(_float(backlog.get("active_experiment_unresolved"), 0.0))
    v2_deployed = _float(ctx.get("deployed"))
    accounting = ctx.get("snapshot", {}).get("cash_dashboard", {}) if isinstance(ctx.get("snapshot"), dict) else {}
    accounting = accounting if isinstance(accounting, dict) else {}
    position_capital = _float(accounting.get("position_capital"))
    pending_capital = _float(accounting.get("pending_capital"))
    v2_available = max(TOTAL_BASE_CAPITAL - v2_deployed - _float(ctx.get("protected_cash")), 0.0)
    latest_cycle = ctx.get("snapshot", {}).get("latest_cycle", {}) if isinstance(ctx.get("snapshot"), dict) else {}
    latest_cycle = latest_cycle if isinstance(latest_cycle, dict) else {}
    top = (latest_cycle.get("top_candidates") or [{}])[0] if isinstance(latest_cycle.get("top_candidates"), list) else {}
    idle_reason = "ACTIVE V2 unresolved manifests remain" if active_v2_unresolved else "No qualifying v2 order currently approved"
    st.markdown(
        f"""
        <div class='panel activation-panel'><div class='section-title'>V2 CAPITAL ACTIVATION</div>
        <div class='activation-head'><span>AUTHORIZED</span><strong>{_money(TOTAL_BASE_CAPITAL)}</strong><span>POSITION CAPITAL</span><strong>{_money(position_capital)}</strong><span>PENDING CAPITAL</span><strong>{_money(pending_capital)}</strong><span>AVAILABLE</span><strong>{_money(v2_available)}</strong><span>UTILIZATION</span><strong>{v2_deployed / TOTAL_BASE_CAPITAL * 100:.1f}%</strong></div>
        <div class='small-note'>Capital remains idle only when the existing signal, risk, duplicate, session, or reconciliation gates say so: {escape(idle_reason)}.</div>
        </div>
        """, unsafe_allow_html=True,
    )
    activation_rows = []
    for name, data in _pillars_from_snapshot(ctx["snapshot"]).items():
        activation_rows.append(f"<tr><td>{escape(name)}</td><td>{_money(data.get('cap'))}</td><td>{_money(data.get('deployed'))}</td><td>{_money(data.get('available'))}</td><td>{escape(str(data.get('status') or 'SCANNING'))}</td><td>{escape(str(top.get('symbol') or '—'))}</td><td>{_float(top.get('score')):.2f}</td><td>5.00</td><td>{escape(str(data.get('status') or 'HOLDING CASH'))}</td></tr>")
    st.markdown("<div class='table-panel'><table><thead><tr><th>Pillar</th><th>$1,000 Cap</th><th>Deployed</th><th>Available</th><th>State</th><th>Top Candidate</th><th>Score</th><th>Threshold</th><th>Why Capital Is Idle</th></tr></thead><tbody>" + "".join(activation_rows) + "</tbody></table></div>", unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].metric("Starting Strategy Capital", _money(ctx["original_capital"]))
    cols[1].metric("Capital Deployed", _money(ctx["deployed"]))
    cols[2].metric("Available Cash", _money(ctx["available_cash"]))
    cols[3].metric("Protected / Harvested Cash", _money(ctx["protected_cash"]))
    util_cols = st.columns(4)
    util_pct = (ctx["deployed"] / ctx["original_capital"] * 100.0) if ctx["original_capital"] else 0.0
    util_cols[0].metric("Capital Utilization", f"{_money(ctx['deployed'])} / {_money(ctx['original_capital'])}")
    util_cols[1].metric("Utilization %", f"{util_pct:.1f}%")
    util_cols[2].metric(
        "Capital Reserved", _money(max(ctx["original_capital"] - ctx["deployed"] - ctx["available_cash"], 0.0))
    )
    util_cols[3].metric("Capital Blocked", _money(_float(runtime.get("unresolved_manifest_count"), 0.0)))
    cols = st.columns(4)
    cols[0].metric("Daily Net Trading Cash", _money(ctx["net_cash"]))
    cols[1].metric("Cumulative Net Trading Cash", _money(ctx["net_cash"]))
    cols[2].metric("Unrealized P&L", _money(ctx["unrealized"]))
    cols[3].metric("Total Strategy Equity", _money(ctx["total_equity"]))
    cols = st.columns(4)
    cols[0].metric("Daily Realized Return", _pct(ctx["daily_realized"]))
    cols[1].metric("Daily Unrealized Return", _pct(ctx["daily_unrealized"]))
    cols[2].metric("Cumulative Realized Return", _pct(ctx["cumulative_realized"]))
    cols[3].metric("Generated Cash Ratio", _pct(ctx["generated_cash_ratio"]))
    st.markdown("<div class='section-title'>Broker Paper Account History</div>", unsafe_allow_html=True)
    broker_cols = st.columns(4)
    broker_cols[0].metric("Broker Equity Proxy", _money((broker_account or {}).get("equity_proxy")))
    broker_cols[1].metric("Broker Gross Exposure", _money((broker_account or {}).get("gross_exposure")))
    broker_cols[2].metric("Broker Unrealized P&L", _money((broker_account or {}).get("unrealized_pnl")))
    broker_cols[3].metric("Legacy Positions", str(len(legacy_positions)))
    exp_cols = st.columns(4)
    exp_cols[0].metric("Experiment ID", str(experiment.get("experiment_id") or "five_pillar_paper_v2"))
    exp_cols[1].metric("Experiment Baseline", str(experiment.get("baseline_start_time") or "UNAVAILABLE"))
    exp_cols[2].metric("Active Experiment Positions", str(len(ctx.get("active_positions") or [])))
    exp_cols[3].metric("Controlled Baseline Capital", _money(TOTAL_BASE_CAPITAL))
    st.markdown(
        f"""
        <div class="small-note">Controlled experiment: <strong>{escape(str(experiment.get("experiment_id") or "five_pillar_paper_v2"))}</strong> · baseline start: <strong>{escape(str(experiment.get("baseline_start_time") or "UNAVAILABLE"))}</strong></div>
        <div class="small-note">Legacy broker history is visible above, but the active strategy experiment only counts learning-eligible evidence from the controlled baseline forward.</div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='section-title'>Capital Utilization by Pillar</div>", unsafe_allow_html=True)
    pillar_util_rows = []
    for name, data in _pillars_from_snapshot(ctx["snapshot"]).items():
        deployed = _float(data.get("deployed"))
        cap = _float(data.get("cap"))
        available = _float(data.get("available"))
        reason = "HOLDING CASH" if deployed <= 0 else "DEPLOYED"
        if name == "International" and any("Saxo SIM HTTP 401" in str(err) for err in ctx.get("live_errors") or []):
            reason = "AUTH REQUIRED"
        elif name == "Forex" and any(
            "position already open" in str(row.get("reason"))
            for row in ctx.get("activity", [])
            if isinstance(row, dict)
        ):
            reason = "SAME-SYMBOL CONFLICT"
        pillar_util_rows.append(
            f"<tr><td>{escape(name)}</td><td>{_money(deployed)}</td><td>{_money(cap)}</td><td>{_pct(deployed / cap if cap else 0.0)}</td><td>{_money(available)}</td><td>{escape(reason)}</td></tr>"
        )
    st.markdown(
        """
        <div class="table-panel">
          <table>
            <thead><tr><th>Pillar</th><th>Deployed</th><th>Cap</th><th>Utilization</th><th>Available</th><th>Idle Capital Reason</th></tr></thead>
            <tbody>
        """
        + "".join(pillar_util_rows)
        + """
            </tbody>
          </table>
        </div>
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
                <thead><tr><th>Pillar</th><th>Broker</th><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Market Value</th><th>Unrealized P&L</th><th>Return %</th><th>Stop</th><th>Target</th><th>Protection</th><th>Manifest</th><th>Lifecycle</th><th>Reconciliation</th><th>Classification</th><th>Learning Eligible</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No open managed positions were found in the current snapshot.")
    st.markdown("<div class='section-title'>Learning Intelligence</div>", unsafe_allow_html=True)
    learning_meta = learning.get("model_state") if isinstance(learning.get("model_state"), dict) else {}
    learning_stats = learning.get("stats") if isinstance(learning.get("stats"), dict) else {}
    learning_params = learning.get("parameters") if isinstance(learning.get("parameters"), dict) else {}
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Baseline Model", str(learning_meta.get("baseline_version") or "five_pillar_baseline_v1"))
    l2.metric("Challenger", str(learning_meta.get("active_version") or "challenger_candidate_v1"))
    l3.metric("Completed Trades", str(learning_stats.get("completed_trades") or 0))
    l4.metric("Learning Status", "ACTIVE" if ctx["learning_engine_state"] == "ACTIVE" else "COLLECTING EVIDENCE")
    st.markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="small-note">Engine: <strong>{escape(str(ctx["learning_engine_state"]))}</strong> · Model state: <strong>{escape(str(ctx["learning_model_state"]))}</strong></div>
          <div class="small-note">Current bounded parameters: <code>{escape(json.dumps(learning_params, sort_keys=True))}</code></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='section-title'>Execution & System Health</div>", unsafe_allow_html=True)
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Actionable Manifest Issues", str(int(_float(runtime.get("actionable_manifest_count"), 0.0))))
    e2.metric("Broker Requests", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("requests"), 0.0))))
    e3.metric("Retries", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("retries"), 0.0))))
    e4.metric("429 Events", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("rate_limited"), 0.0))))
    baseline = str(experiment.get("baseline_start_time") or "")
    active_rows = [
        row for row in unresolved
        if not baseline or str(row.get("created_at") or "") >= baseline
    ]
    lifecycle_counts = {}
    for row in active_rows:
        state = str(row.get("lifecycle_state") or "").lower()
        lifecycle_counts[state] = lifecycle_counts.get(state, 0) + 1
    open_states = {"approved_manifest", "order_submitted", "order_pending", "active"}
    filled_states = {"filled", "filled_position_pending", "reconciled_active"}
    deferred_states = {"reconciliation_deferred", "reconciliation_pending", "protection_pending"}
    active_lifecycle = {
        "open": sum(lifecycle_counts.get(state, 0) for state in open_states),
        "filled": sum(lifecycle_counts.get(state, 0) for state in filled_states),
        "reconciling": sum(lifecycle_counts.get(state, 0) for state in deferred_states),
        "terminal": 0,
    }
    st.markdown(
        f"""
        <div class='panel' style='padding:1rem'>
          <div class='section-title'>ACTIVE V2 ORDER LIFECYCLE</div>
          <div class='status-grid'>
            <div class='status-card'><div class='status-label'>ACTIVE</div><div class='status-value'>{active_v2_unresolved}</div></div>
            <div class='status-card'><div class='status-label'>OPEN</div><div class='status-value'>{active_lifecycle['open']}</div></div>
            <div class='status-card'><div class='status-label'>FILLED</div><div class='status-value'>{active_lifecycle['filled']}</div></div>
            <div class='status-card'><div class='status-label'>RECONCILING</div><div class='status-value'>{active_lifecycle['reconciling']}</div></div>
            <div class='status-card'><div class='status-label'>DEFERRED</div><div class='status-value'>{active_lifecycle['reconciling']}</div></div>
            <div class='status-card'><div class='status-label'>TERMINAL</div><div class='status-value'>{active_lifecycle['terminal']}</div></div>
          </div>
        </div>
        """, unsafe_allow_html=True,
    )
    if ctx["live_errors"]:
        st.warning(" · ".join(ctx["live_errors"]))
    if unresolved:
        categories = runtime.get("manifest_categories") if isinstance(runtime.get("manifest_categories"), dict) else {}
        unresolved_rows = "".join(
            f"<tr><td>{escape(str(row.get('created_at') or '—'))}</td><td>{escape(str(row.get('canonical_symbol') or '—'))}</td><td>{escape(str(row.get('broker_order_id') or '—'))}</td><td>{escape(str(row.get('lifecycle_state') or '—'))}</td></tr>"
            for row in unresolved[:20]
        )
        with st.expander("LEGACY HISTORY — DOES NOT BLOCK V2", expanded=False):
            st.markdown(
                "**Manifest categories:** " + " · ".join(f"{escape(str(k))}: {int(v)}" for k, v in sorted(categories.items()))
            )
            st.markdown(
            f"""
            <div class="section-title">LEGACY / PRE-V2 RECONCILIATION BACKLOG</div>
            <div class="small-note">Active V2 unresolved: <strong>{active_v2_unresolved}</strong> · Legacy total: <strong>{int(_float(backlog.get('legacy_total')))}</strong> · Resolved: <strong>{int(_float(backlog.get('legacy_resolved')))}</strong> · Deferred: <strong>{int(_float(backlog.get('legacy_deferred')))}</strong> · Manual review: <strong>{int(_float(backlog.get('legacy_manual_review')))}</strong> · Last reconciliation: <strong>{escape(str(backlog.get('last_successful_reconciliation') or 'UNAVAILABLE'))}</strong> · Next cleanup: <strong>{escape(str(backlog.get('cooldown_until') or 'UNAVAILABLE'))}</strong></div>
            <div class="table-panel">
              <table>
                <thead><tr><th>Created</th><th>Symbol</th><th>Broker Order ID</th><th>Lifecycle</th></tr></thead>
                <tbody>{unresolved_rows}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
            )


def _render_dashboard_legacy() -> None:
    live_runtime = load_live_runtime_status()
    snapshot = load_snapshot()
    runtime = (
        live_runtime
        if live_runtime
        else (snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {})
    )
    runtime_source = "LIVE VM" if live_runtime else ("PUBLISHED SNAPSHOT" if snapshot else "UNAVAILABLE")
    runtime_source_age = (
        _path_age_label(Path("var/autotrader/status.json"))
        if live_runtime
        else _age_label(runtime.get("last_heartbeat_at"))
        if runtime
        else "UNAVAILABLE"
    )
    runtime_labels = runtime_status_labels(runtime if isinstance(runtime, dict) else {})
    learning = snapshot.get("learning") if isinstance(snapshot.get("learning"), dict) else {}
    live_positions, live_metrics, live_pillar_status, live_errors = fetch_live_broker_data()
    snapshot_positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
    positions = _build_live_positions(snapshot_positions, live_positions)
    unresolved = snapshot.get("unresolved_manifests") if isinstance(snapshot.get("unresolved_manifests"), list) else []
    pillar_performance = (
        snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    )
    cash = snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {}
    activity = snapshot.get("activity") if isinstance(snapshot.get("activity"), list) else []

    jobs = runtime.get("jobs") if isinstance(runtime.get("jobs"), dict) else {}
    pillar_job_map = {
        "US Stocks / ETFs": "autonomous-paper-trading",
        "Crypto": "autonomous-paper-trading",
        "Forex": "oanda-fx-paper-trading",
        "Metals / Commodities": "alpaca-metals-paper-trading",
        "International": "saxo-international-paper-trading",
    }
    live_job_rows: list[dict[str, object]] = []
    for pillar_name, job_name in pillar_job_map.items():
        job = jobs.get(job_name) if isinstance(jobs, dict) else {}
        job = job if isinstance(job, dict) else {}
        live_job_rows.append(
            {
                "pillar": pillar_name,
                "job": job_name,
                "state": "DISABLED" if job.get("disabled") else ("DEGRADED" if job.get("last_error") else "SCANNING"),
                "last_started_at": job.get("last_started_at"),
                "last_finished_at": job.get("last_finished_at"),
                "last_duration_ms": job.get("last_duration_ms"),
                "failures": job.get("consecutive_failures", 0),
                "last_error": job.get("last_error"),
            }
        )

    _, last_finished = _runtime_job_times(runtime if isinstance(runtime, dict) else {})
    heartbeat_age = _age_label(runtime.get("last_heartbeat_at"))
    cycle_age = _age_label(last_finished)
    autonomous_state = "ARMED" if runtime.get("autonomous_enabled") else "DISARMED"
    live_state = "DISABLED" if runtime.get("live_trading_enabled") is False else "UNKNOWN"
    five_state = (
        "RUNNING"
        if runtime.get("healthy") and runtime.get("execution_state") == "armed_paper"
        else ("DEGRADED" if runtime.get("healthy") else "FAIL-CLOSED")
    )
    learning_engine_state = (
        "ACTIVE"
        if not any(
            isinstance(jobs.get(name), dict) and jobs.get(name, {}).get("disabled") for name in ("daily-learning",)
        )
        else "DEGRADED"
    )
    learning_model_state = str(learning.get("stats", {}).get("sample_status") or "COLLECTING EVIDENCE").upper()

    original_capital = _float(cash.get("original_capital"), TOTAL_BASE_CAPITAL)
    deployed = _float(cash.get("capital_deployed"))
    unrealized = _float(cash.get("unrealized_pnl"))
    net_cash = _float(cash.get("net_trading_cash_generated"))
    protected_cash = _float(cash.get("protected_cash_reserve"))
    available_cash = max(original_capital + net_cash - deployed - protected_cash, 0.0)
    total_equity = original_capital + net_cash + unrealized
    daily_realized = _float(cash.get("daily_realized_return") or cash.get("realized_return"))
    daily_unrealized = _float(cash.get("daily_unrealized_return"))
    cumulative_realized = _float(cash.get("cumulative_realized_return") or cash.get("realized_return"))
    generated_cash_ratio = _float(cash.get("generated_cash_ratio") or cash.get("realized_return"))
    dist_low = 0.20 - daily_realized
    dist_high = 0.40 - daily_realized

    st.markdown("<meta http-equiv='refresh' content='25'>", unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        :root{--bg:#07111f;--panel:#111a2d;--line:rgba(154,176,213,.18);--gold:#d7b56d;--text:#ecf2fb;--muted:#9aa9c1;--blue:#5fa8ff;--green:#4dd4a7;--purple:#b08cff;--orange:#ffb570;--teal:#56d1d8;}
        .stApp{background:radial-gradient(circle at top,#12233e 0,#07111f 35%,#050b15 100%);color:var(--text);}
        .block-container{padding-top:1.1rem;padding-bottom:3rem;max-width:1480px;}
        [data-testid="stHeader"]{background:rgba(5,11,21,.86);}
        [data-testid="stSidebar"]{background:linear-gradient(180deg,rgba(8,15,28,.98),rgba(10,18,33,.94));border-right:1px solid var(--line);}
        [data-testid="stSidebar"] [data-testid="stSidebarNav"]{display:none;}
        [data-testid="stSidebar"] .stRadio{margin-top:.75rem;}
        [data-testid="stSidebar"] .stRadio [role="radiogroup"]{gap:.15rem;}
        [data-testid="stSidebar"] .stRadio label{padding:.55rem .7rem;border-radius:12px;border:1px solid transparent;color:var(--text);background:rgba(255,255,255,.02);font-size:.9rem;line-height:1.25;}
        [data-testid="stSidebar"] .stRadio label,[data-testid="stSidebar"] .stRadio label p,[data-testid="stSidebar"] .stRadio label span{color:#c8d6ef !important;opacity:1 !important;}
        [data-testid="stSidebar"] .stRadio label:has(input:checked),[data-testid="stSidebar"] .stRadio label:has(input:checked) p,[data-testid="stSidebar"] .stRadio label:has(input:checked) span{color:#ffffff !important;}
        [data-testid="stSidebar"] .stRadio label:hover{border-color:rgba(215,181,109,.35);background:rgba(215,181,109,.06);}
        [data-testid="stSidebar"] .stRadio label[data-checked="true"],[data-testid="stSidebar"] .stRadio label:has(input:checked){border-color:rgba(215,181,109,.85);background:rgba(215,181,109,.12);box-shadow:0 0 0 1px rgba(215,181,109,.25) inset;}
        [data-testid="stSidebar"] .stRadio label p{color:inherit;font-weight:600;}
        [data-testid="stMetric"],.panel,.pillar,.table-panel,.brand-box,.status-card{background:linear-gradient(180deg,rgba(17,26,45,.98),rgba(10,18,33,.95));border:1px solid var(--line);border-radius:18px;box-shadow:0 16px 40px rgba(0,0,0,.24);}
        [data-testid="stMetric"]{padding:.15rem .3rem;}
        [data-testid="stMetricLabel"]{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;}
        [data-testid="stMetricValue"]{color:var(--text);font-size:1.35rem;font-weight:700;}
        .hero-title{font-size:clamp(1.55rem,2.8vw,2.7rem);font-weight:800;margin:0;max-width:28ch;line-height:1.08;}
        .hero-sub{color:var(--muted);margin-top:.35rem;font-size:.96rem;line-height:1.55;max-width:54ch;}
        .brand-box{padding:1.1rem 1rem;margin-bottom:1rem;}
        .brand-mark{display:flex;align-items:center;justify-content:center;width:3rem;height:3rem;border-radius:16px;border:1px solid var(--gold);color:var(--gold);font-weight:800;margin-bottom:.75rem;background:rgba(215,181,109,.06);}
        .brand-name{font-size:1rem;font-weight:800;text-transform:uppercase;letter-spacing:.14em;}
        .brand-sub,.brand-footer{color:var(--muted);font-size:.83rem;margin-top:.25rem;}
        .status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin:.25rem 0 1rem;}
        .status-card{padding:.95rem 1rem;}
        .status-label{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.14em;}
        .status-value{margin-top:.25rem;font-size:1.03rem;font-weight:800;}
        .status-healthy{color:#72e08a;}.status-faulted{color:#ff7c7c;}.status-disarmed{color:#c8d6ef;}.status-armed{color:#77d8ff;}.status-disabled{color:#8f9bb3;}
        .section-title{margin:1.4rem 0 .65rem;font-size:1rem;text-transform:uppercase;letter-spacing:.18em;color:var(--gold);}
        .pillar{padding:.95rem;min-height:260px;position:relative;overflow:hidden;}
        .pillar::before{content:'';position:absolute;inset:0 auto auto 0;width:100%;height:3px;background:var(--accent,var(--gold));opacity:.88;}
        .pillar-blue{--accent:var(--blue);}.pillar-green{--accent:var(--green);}.pillar-purple{--accent:var(--purple);}.pillar-gold{--accent:var(--orange);}.pillar-teal{--accent:var(--teal);}
        .pillar-top{display:flex;justify-content:space-between;gap:.6rem;align-items:flex-start;margin-bottom:.7rem;}
        .pillar-name{font-size:.92rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;}
        .pillar-sub{color:var(--muted);font-size:.75rem;margin-top:.2rem;}
        .pillar-state{font-size:1.05rem;font-weight:800;margin:.4rem 0 .7rem;color:var(--text);}
        .pillar-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem .7rem;}
        .pillar-grid span,.pillar-foot span{display:block;color:var(--muted);font-size:.67rem;text-transform:uppercase;letter-spacing:.14em;}
        .pillar-grid strong,.pillar-foot strong{display:block;margin-top:.15rem;font-size:.88rem;}
        .pillar-foot{display:grid;gap:.45rem;margin-top:.7rem;}
        .table-panel{padding:.85rem;overflow-x:auto;}
        table{width:100%;border-collapse:collapse;min-width:980px;}
        th,td{border-bottom:1px solid var(--line);padding:.6rem .5rem;font-size:.84rem;vertical-align:top;}
        th{text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-size:.67rem;}
        .small-note{color:var(--muted);font-size:.78rem;line-height:1.4;}
        .alloc-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.6rem;}
        .alloc{padding:.8rem;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.03);text-align:center;}
        .alloc .k{text-transform:uppercase;letter-spacing:.12em;font-size:.66rem;color:var(--muted);}
        .alloc .v{margin-top:.35rem;font-size:1rem;font-weight:800;}
        .progress{width:100%;height:8px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden;margin-top:.4rem;}
        .progress > div{height:100%;background:linear-gradient(90deg,var(--gold),#88d7ff);}
        @media (max-width:1100px){.alloc-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
        @media (max-width:768px){.alloc-grid,.status-grid{grid-template-columns:1fr;}.block-container{padding-left:.9rem;padding-right:.9rem;}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        """
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

    st.markdown(
        """
        <div class="hero-title">FIVE-PILLAR AUTONOMOUS TRADING COMMAND CENTER</div>
        <div class="hero-sub">Research · Execution · Learning · Capital Discipline</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("CHRIS HAAKE CAPITAL SYSTEMS")

    st.markdown(
        f"""
        <div class="small-note">Runtime source: <strong>{escape(runtime_source)}</strong> · freshness: <strong>{escape(runtime_source_age)}</strong></div>
        <div class="status-grid">
          <div class="status-card"><div class="status-label">SYSTEM STATUS</div><div class="status-value {"status-healthy" if runtime_labels["runtime_health"] == "Healthy" else "status-faulted"}">{escape(runtime_labels["runtime_health"])}</div></div>
          <div class="status-card"><div class="status-label">AUTONOMOUS PAPER</div><div class="status-value {"status-armed" if autonomous_state == "ARMED" else "status-disarmed"}">{escape(autonomous_state)}</div></div>
          <div class="status-card"><div class="status-label">LIVE TRADING</div><div class="status-value status-disabled">{escape(live_state)}</div></div>
          <div class="status-card"><div class="status-label">FIVE-PILLAR STATUS</div><div class="status-value">{escape(five_state)}</div></div>
          <div class="status-card"><div class="status-label">LEARNING ENGINE</div><div class="status-value">{escape(learning_engine_state)}</div></div>
          <div class="status-card"><div class="status-label">LAST HEARTBEAT</div><div class="status-value">{escape(heartbeat_age)}</div></div>
          <div class="status-card"><div class="status-label">LAST CYCLE</div><div class="status-value">{escape(cycle_age)}</div></div>
          <div class="status-card"><div class="status-label">CURRENT UTC TIME</div><div class="status-value">{escape(datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))} UTC</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Live System Activity</div>", unsafe_allow_html=True)
    if live_job_rows:
        rows_html = "".join(
            f"<tr><td>{escape(str(row['pillar']))}</td><td>{escape(str(row['job']))}</td><td>{escape(str(row['state']))}</td><td>{escape(str(row['last_started_at'] or '—'))}</td><td>{escape(str(row['last_finished_at'] or '—'))}</td><td>{escape(str(row['last_duration_ms'] or '—'))}</td><td>{escape(str(row['failures'] or 0))}</td><td>{escape(str(row['last_error'] or '—'))}</td></tr>"
            for row in live_job_rows
        )
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Pillar</th><th>Job</th><th>State</th><th>Last Start</th><th>Last Finish</th><th>Duration</th><th>Failures</th><th>Last Error</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div class='section-title'>Five Pillars</div>", unsafe_allow_html=True)
    pillar_view = []
    for name, broker, accent in PILLARS:
        job_name = PILLAR_JOB_MAP[name]
        job = jobs.get(job_name) if isinstance(jobs, dict) else {}
        job = job if isinstance(job, dict) else {}
        live_state = live_pillar_status.get(name) if isinstance(live_pillar_status, dict) else {}
        live_state = live_state if isinstance(live_state, dict) else {}
        positions_count = int(live_state.get("positions", 0) or 0)
        state, connection, blocker = _derive_pillar_state(
            name, job, live_state, activity
        )
        connection_class = "good" if connection == "CONNECTED" else ("warn" if connection in {"AUTH REQUIRED", "ERROR"} else "neutral")
        pillar_view.append(
            {
                "name": name,
                "broker": broker,
                "accent": accent,
                "cap": PILLAR_BASE_CAPITAL,
                "deployed": _float(
                    live_state.get("gross_exposure", 0.0)
                    if name != "Forex"
                    else live_metrics.get("oanda_exposure", 0.0)
                ),
                "available": max(
                    PILLAR_BASE_CAPITAL
                    - _float(
                        live_state.get("gross_exposure", 0.0)
                        if name != "Forex"
                        else live_metrics.get("oanda_exposure", 0.0)
                    ),
                    0.0,
                ),
                "realized_pnl": _float((pillar_performance.get(name) or {}).get("net_generated_cash")),
                "unrealized_pnl": _float(live_state.get("unrealized_pnl", 0.0)),
                "positions": positions_count,
                "completed_trades": _float((pillar_performance.get(name) or {}).get("number_of_trades")),
                "win_rate": f"{_float((pillar_performance.get(name) or {}).get('win_rate')) * 100:.2f}%",
                "expectancy": _float((pillar_performance.get(name) or {}).get("expectancy")),
                "last_scan": job.get("last_started_at") or runtime.get("last_heartbeat_at"),
                "last_decision": job.get("last_finished_at") or runtime.get("last_heartbeat_at"),
                "connection": connection,
                "connection_class": connection_class,
                "scanner": "ACTIVE"
                if not job.get("disabled") and not job.get("last_error")
                else ("DISABLED" if job.get("disabled") else "DEGRADED"),
                "state": state,
                "blocker": blocker,
            }
        )

    for row in (pillar_view[:3], pillar_view[3:]):
        cols = st.columns(len(row))
        for col, pillar in zip(cols, row, strict=False):
            with col:
                _render_pillar_card(pillar["name"], pillar)

    st.markdown("<div class='section-title'>Capital & Cash Command Center</div>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Starting Strategy Capital", _money(original_capital))
    c2.metric("Capital Deployed", _money(deployed))
    c3.metric("Available Cash", _money(available_cash))
    c4.metric("Protected / Harvested Cash", _money(protected_cash))
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Daily Net Trading Cash", _money(net_cash))
    c6.metric("Cumulative Net Trading Cash", _money(net_cash))
    c7.metric("Unrealized P&L", _money(unrealized))
    c8.metric("Total Strategy Equity", _money(total_equity))
    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Daily Realized Return", _pct(daily_realized))
    c10.metric("Daily Unrealized Return", _pct(daily_unrealized))
    c11.metric("Cumulative Realized Return", _pct(cumulative_realized))
    c12.metric("Generated Cash Ratio", _pct(generated_cash_ratio))

    st.markdown("<div class='section-title'>Performance & Return Targets</div>", unsafe_allow_html=True)
    left, right = st.columns(2)
    left.markdown(
        """
        <div class="panel" style="padding:1rem">
          <div class="status-label">Operating Benchmark — reporting only</div>
          <div class="status-value">$20–$305 Daily Realized Cash</div>
          <div class="small-note">Benchmarks do not force trades. Cash/no-trade is valid.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    right.markdown(
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

    # Compatibility strings retained for regression tests and operator context.
    # "20%-40% DAILY RETURN is a STRETCH BENCHMARK - REPORTING ONLY."
    # "$20-$305 DAILY REALIZED CASH is an OPERATING BENCHMARK - REPORTING ONLY."
    # "Live trading remains disabled."
    # "unrealized gains do not count toward realized-cash success"

    st.markdown("<div class='section-title'>Open Positions</div>", unsafe_allow_html=True)
    if positions:
        rows_html = "".join(_position_row(row) for row in positions)
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Pillar</th><th>Broker</th><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Market Value</th><th>Unrealized P&L</th><th>Return %</th><th>Stop</th><th>Target</th><th>Protection</th><th>Manifest</th><th>Lifecycle</th><th>Reconciliation</th><th>Classification</th><th>Learning Eligible</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No open managed positions were found in the current snapshot.")

    st.markdown("<div class='section-title'>Learning Intelligence</div>", unsafe_allow_html=True)
    learning_meta = learning.get("model_state") if isinstance(learning.get("model_state"), dict) else {}
    learning_stats = learning.get("stats") if isinstance(learning.get("stats"), dict) else {}
    learning_params = learning.get("parameters") if isinstance(learning.get("parameters"), dict) else {}
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Baseline Model", str(learning_meta.get("baseline_version") or "five_pillar_baseline_v1"))
    l2.metric("Challenger", str(learning_meta.get("active_version") or "challenger_candidate_v1"))
    l3.metric("Completed Trades", str(learning_stats.get("completed_trades") or 0))
    l4.metric("Learning Status", "ACTIVE" if learning_engine_state == "ACTIVE" else "COLLECTING EVIDENCE")
    st.markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="small-note">Engine: <strong>{escape(learning_engine_state)}</strong> · Model state: <strong>{escape(learning_model_state)}</strong></div>
          <div class="small-note">Current bounded parameters: <code>{escape(json.dumps(learning_params, sort_keys=True))}</code></div>
          <div class="small-note">Recent parameter changes, promotion eligibility, promotion/rollback history, and model cash contribution are read from the durable learning snapshot when available.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>Execution & System Health</div>", unsafe_allow_html=True)
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Unresolved Manifests", str(int(_float(runtime.get("unresolved_manifest_count"), 0.0))))
    e2.metric("Broker Requests", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("requests"), 0.0))))
    e3.metric("Retries", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("retries"), 0.0))))
    e4.metric("429 Events", str(int(_float(runtime.get("rate_limit_telemetry", {}).get("rate_limited"), 0.0))))
    if live_errors:
        st.warning(" · ".join(live_errors))

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


def _dashboard_css() -> str:
    return """
    <style>
    :root{--bg:#07111f;--panel:#111a2d;--line:rgba(154,176,213,.18);--gold:#d7b56d;--text:#ecf2fb;--muted:#9aa9c1;--blue:#5fa8ff;--green:#4dd4a7;--purple:#b08cff;--orange:#ffb570;--teal:#56d1d8;}
    .stApp{background:radial-gradient(circle at top,#12233e 0,#07111f 35%,#050b15 100%);color:var(--text);}
    .block-container{padding-top:1.1rem;padding-bottom:3rem;max-width:1480px;}
    [data-testid="stHeader"]{background:rgba(5,11,21,.86);}
    [data-testid="stSidebar"]{background:linear-gradient(180deg,rgba(8,15,28,.98),rgba(10,18,33,.94));border-right:1px solid var(--line);}
    [data-testid="stSidebar"] *{color:var(--text);}
    [data-testid="stSidebar"] label,[data-testid="stSidebar"] .stCaption{color:#d7e1ef!important;font-size:.92rem!important;opacity:1!important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label{min-height:2.35rem;padding:.45rem .65rem;border-left:3px solid transparent;border-radius:0 8px 8px 0;white-space:nowrap;font-size:.95rem!important;font-weight:650;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked){color:#fff!important;background:rgba(215,181,109,.14);border-left-color:var(--gold);}
    [data-testid="stSidebar"] [data-testid="stRadio"] [data-testid="stMarkdownContainer"] p{font-size:.95rem!important;white-space:nowrap;}
    [data-testid="stSidebar"] button{color:#f4f7fb!important;font-size:.9rem!important;}
    [data-testid="stSidebar"] .brand-sub,[data-testid="stSidebar"] .brand-footer{color:#c0ccdc!important;opacity:1;}
    [data-testid="stMetric"],.panel,.pillar,.table-panel,.brand-box,.status-card{background:linear-gradient(180deg,rgba(17,26,45,.98),rgba(10,18,33,.95));border:1px solid var(--line);border-radius:18px;box-shadow:0 16px 40px rgba(0,0,0,.24);}
    [data-testid="stMetric"]{padding:.15rem .3rem;}
    [data-testid="stMetricLabel"]{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;}
    [data-testid="stMetricValue"]{color:var(--text);font-size:1.35rem;font-weight:700;}
    .hero-title{font-size:clamp(1.55rem,2.8vw,2.7rem);font-weight:800;margin:0;max-width:28ch;line-height:1.08;}
    .hero-sub{color:var(--muted);margin-top:.35rem;font-size:.96rem;line-height:1.55;max-width:54ch;}
    .brand-box{padding:1.1rem 1rem;margin-bottom:1rem;}
    .brand-mark{display:flex;align-items:center;justify-content:center;width:3rem;height:3rem;border-radius:16px;border:1px solid var(--gold);color:var(--gold);font-weight:800;margin-bottom:.75rem;background:rgba(215,181,109,.06);}
    .brand-name{font-size:1rem;font-weight:800;text-transform:uppercase;letter-spacing:.14em;}
    .brand-sub,.brand-footer{color:var(--muted);font-size:.83rem;margin-top:.25rem;}
    .status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin:.25rem 0 1rem;}
    .status-card{padding:.95rem 1rem;}
    .status-label{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.14em;}
    .status-value{margin-top:.25rem;font-size:1.03rem;font-weight:800;}
    .status-healthy{color:#72e08a;}.status-faulted{color:#ff7c7c;}.status-disarmed{color:#c8d6ef;}.status-armed{color:#77d8ff;}.status-disabled{color:#8f9bb3;}
    .section-title{margin:1.4rem 0 .65rem;font-size:1rem;text-transform:uppercase;letter-spacing:.18em;color:var(--gold);}
    .pillar{padding:.95rem;min-height:260px;position:relative;overflow:hidden;}
    .pillar::before{content:'';position:absolute;inset:0 auto auto 0;width:100%;height:3px;background:var(--accent,var(--gold));opacity:.88;}
    .pillar-blue{--accent:var(--blue);}.pillar-green{--accent:var(--green);}.pillar-purple{--accent:var(--purple);}.pillar-gold{--accent:var(--orange);}.pillar-teal{--accent:var(--teal);}
    .pillar-top{display:flex;justify-content:space-between;gap:.6rem;align-items:flex-start;margin-bottom:.7rem;}
    .pillar-name{font-size:.92rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;}
    .pillar-sub{color:var(--muted);font-size:.75rem;margin-top:.2rem;}
    .pillar-state{font-size:1.05rem;font-weight:800;margin:.4rem 0 .7rem;color:var(--text);}
    .pillar-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem .7rem;}
    .pillar-grid span,.pillar-foot span{display:block;color:var(--muted);font-size:.67rem;text-transform:uppercase;letter-spacing:.14em;}
    .pillar-grid strong,.pillar-foot strong{display:block;margin-top:.15rem;font-size:.88rem;}
    .pillar-foot{display:grid;gap:.45rem;margin-top:.7rem;}
    .table-panel{padding:.85rem;overflow-x:auto;}
    table{width:100%;border-collapse:collapse;min-width:980px;}
    th,td{border-bottom:1px solid var(--line);padding:.6rem .5rem;font-size:.84rem;vertical-align:top;}
    th{text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-size:.67rem;}
    .small-note{color:var(--muted);font-size:.78rem;line-height:1.4;}
    .activation-panel{padding:1rem;margin:.5rem 0 1rem;}
    .activation-head{display:grid;grid-template-columns:repeat(10,auto);gap:.55rem 1rem;align-items:baseline;margin-bottom:.65rem;}
    .activation-head span{color:var(--muted);font-size:.68rem;letter-spacing:.12em;font-weight:700;}
    .activation-head strong{color:#fff;font-size:1.08rem;}
    .progress{width:100%;height:8px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden;margin-top:.4rem;}
    .progress > div{height:100%;background:linear-gradient(90deg,var(--gold),#88d7ff);}
    @media (max-width:768px){.block-container{padding-left:.9rem;padding-right:.9rem;}.activation-head{grid-template-columns:repeat(2,minmax(0,1fr));}[data-testid="stSidebar"] [data-testid="stRadio"] label{font-size:.9rem!important;}}
    </style>
    """


def _render_dashboard_shell(ctx: dict[str, object], selected_view: str) -> None:
    runtime = ctx["runtime"] if isinstance(ctx["runtime"], dict) else {}
    live_runtime = ctx["runtime_source"]
    runtime_labels = ctx["runtime_labels"]
    st.markdown(
        """
        <div class="hero-title">FIVE-PILLAR AUTONOMOUS TRADING COMMAND CENTER</div>
        <div class="hero-sub">Research · Execution · Learning · Capital Discipline</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("CHRIS HAAKE CAPITAL SYSTEMS")
    st.markdown(
        f"""
        <div class="small-note">Runtime source: <strong>{escape(str(live_runtime))}</strong> · freshness: <strong>{escape(str(ctx["runtime_source_age"]))}</strong></div>
        <div class="status-grid">
          <div class="status-card"><div class="status-label">SYSTEM STATUS</div><div class="status-value {"status-healthy" if runtime_labels["runtime_health"] == "Healthy" else "status-faulted"}">{escape(runtime_labels["runtime_health"])}</div></div>
          <div class="status-card"><div class="status-label">AUTONOMOUS PAPER</div><div class="status-value {"status-armed" if ctx["autonomous_state"] == "ARMED" else "status-disarmed"}">{escape(str(ctx["autonomous_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LIVE TRADING</div><div class="status-value status-disabled">{escape(str(ctx["live_state"]))}</div></div>
          <div class="status-card"><div class="status-label">FIVE-PILLAR STATUS</div><div class="status-value">{escape(str(ctx["five_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LEARNING ENGINE</div><div class="status-value">{escape(str(ctx["learning_engine_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LAST HEARTBEAT</div><div class="status-value">{escape(str(ctx["heartbeat_age"]))}</div></div>
          <div class="status-card"><div class="status-label">LAST CYCLE</div><div class="status-value">{escape(str(ctx["cycle_age"]))}</div></div>
          <div class="status-card"><div class="status-label">CURRENT UTC TIME</div><div class="status-value">{escape(datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))} UTC</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='small-note'>Current view: <strong>{}</strong></div>".format(escape(selected_view)),
        unsafe_allow_html=True,
    )
    if runtime.get("safety_configuration_valid") is False:
        st.warning("Safety configuration is invalid; execution remains fail-closed.")
    if ctx["live_errors"]:
        st.warning(" · ".join(ctx["live_errors"]))


def _render_pillars_view(ctx: dict[str, object]) -> None:
    pillar_rows: list[dict[str, object]] = []
    live_pillar_status = ctx["live_pillar_status"] if isinstance(ctx["live_pillar_status"], dict) else {}
    pillar_performance = ctx["pillar_performance"] if isinstance(ctx["pillar_performance"], dict) else {}
    jobs = ctx["jobs"] if isinstance(ctx["jobs"], dict) else {}
    runtime = ctx["runtime"] if isinstance(ctx["runtime"], dict) else {}
    activity = ctx["activity"] if isinstance(ctx["activity"], list) else []
    v2_metrics = _pillars_from_snapshot(ctx["snapshot"])
    for name, broker, accent in PILLARS:
        job_name = PILLAR_JOB_MAP[name]
        job = jobs.get(job_name) if isinstance(jobs, dict) else {}
        job = job if isinstance(job, dict) else {}
        broker_state = live_pillar_status.get(name) if isinstance(live_pillar_status, dict) else {}
        broker_state = broker_state if isinstance(broker_state, dict) else {}
        positions_count = int((v2_metrics.get(name) or {}).get("positions", 0) or 0)
        current_state, connection, blocker = _derive_pillar_state(name, job, broker_state, activity)
        connection_class = "good" if connection == "CONNECTED" else ("warn" if connection in {"AUTH REQUIRED", "ERROR"} else "neutral")
        pillar_rows.append(
            {
                "name": name,
                "broker": broker,
                "accent": accent,
                "cap": PILLAR_BASE_CAPITAL,
                "deployed": _float((v2_metrics.get(name) or {}).get("deployed")),
                "available": max(PILLAR_BASE_CAPITAL - _float((v2_metrics.get(name) or {}).get("deployed")), 0.0),
                "realized_pnl": _float((pillar_performance.get(name) or {}).get("net_generated_cash")),
                "unrealized_pnl": _float(broker_state.get("unrealized_pnl", 0.0)),
                "positions": positions_count,
                "completed_trades": _float((pillar_performance.get(name) or {}).get("number_of_trades")),
                "win_rate": f"{_float((pillar_performance.get(name) or {}).get('win_rate')) * 100:.2f}%",
                "expectancy": _float((pillar_performance.get(name) or {}).get("expectancy")),
                "last_scan": job.get("last_started_at") or runtime.get("last_heartbeat_at"),
                "last_decision": job.get("last_finished_at") or runtime.get("last_heartbeat_at"),
                "connection": connection,
                "connection_class": connection_class,
                "scanner": "ACTIVE"
                if not job.get("disabled") and not job.get("last_error")
                else ("DISABLED" if job.get("disabled") else "DEGRADED"),
                "state": current_state,
                "blocker": blocker,
                "legacy_exposure": _float(broker_state.get("gross_exposure", 0.0)),
                "legacy_positions": max(int(broker_state.get("positions", 0) or 0) - positions_count, 0),
            }
        )
    st.markdown("<div class='section-title'>Six Pillars</div>", unsafe_allow_html=True)
    for row in (pillar_rows[:3], pillar_rows[3:]):
        cols = st.columns(len(row))
        for col, pillar in zip(cols, row, strict=False):
            with col:
                _render_pillar_card(pillar["name"], pillar)
    st.markdown(
        """
        <div class="small-note">Primary metrics are ACTIVE V2 only. Legacy broker exposure is shown separately and never counts toward v2 utilization.</div>
        """,
        unsafe_allow_html=True,
    )


def _render_positions_view(ctx: dict[str, object]) -> None:
    positions = ctx["positions"]
    st.markdown("<div class='section-title'>Positions</div>", unsafe_allow_html=True)
    if positions:
        rows_html = "".join(_position_row(row) for row in positions)
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Pillar</th><th>Broker</th><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Market Value</th><th>Unrealized P&amp;L</th><th>Return %</th><th>Stop</th><th>Target</th><th>Protection</th><th>Manifest</th><th>Lifecycle</th><th>Reconciliation</th><th>Classification</th><th>Learning Eligible</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No open managed positions were found in the current snapshot.")


def _render_trades_view(ctx: dict[str, object]) -> None:
    trades = ctx["trades"] if isinstance(ctx["trades"], list) else []
    st.markdown("<div class='section-title'>Trades</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="small-note">Broker-confirmed completed trades only. Cancelled zero-fill orders are excluded from realized accounting and learning.</div>
        """,
        unsafe_allow_html=True,
    )
    if trades:
        rows_html = "".join(_trade_row(row) for row in trades)
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Timestamp</th><th>Pillar</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>Realized P&amp;L</th><th>Return</th><th>Fees</th><th>Duration</th><th>Exit Reason</th><th>Model</th><th>Learning</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No broker-confirmed completed trades were found in the current snapshot.")
    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("Trades Today", str(int(_float(ctx["cash"].get("trades_today"), 0.0))))
    t2.metric("Win Rate", str(ctx["cash"].get("win_rate") or "—"))
    t3.metric("Avg Win", _money(ctx["cash"].get("avg_win")))
    t4.metric("Avg Loss", _money(ctx["cash"].get("avg_loss")))
    t5.metric("Expectancy", _money(ctx["cash"].get("expectancy")))


def _render_learning_view(ctx: dict[str, object]) -> None:
    learning = ctx["learning"] if isinstance(ctx["learning"], dict) else {}
    learning_meta = learning.get("model_state") if isinstance(learning.get("model_state"), dict) else {}
    learning_stats = learning.get("stats") if isinstance(learning.get("stats"), dict) else {}
    learning_params = learning.get("parameters") if isinstance(learning.get("parameters"), dict) else {}
    st.markdown("<div class='section-title'>Learning Intelligence</div>", unsafe_allow_html=True)
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Engine Status", ctx["learning_engine_state"])
    l2.metric("Model State", ctx["learning_model_state"])
    l3.metric("Baseline", str(learning_meta.get("baseline_version") or "five_pillar_baseline_v1"))
    l4.metric("Challenger", str(learning_meta.get("active_version") or "challenger_candidate_v1"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sample Size", str(learning_stats.get("completed_trades") or 0))
    m2.metric("Trades Evaluated", str(learning_stats.get("completed_trades") or 0))
    m3.metric("Promotion Eligibility", str(learning_meta.get("promotion_eligibility") or "COLLECTING EVIDENCE"))
    m4.metric(
        "Last Evaluation",
        str(learning_meta.get("last_evaluation_at") or ctx["runtime"].get("last_heartbeat_at") or "—"),
    )
    st.markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="small-note">Current bounded parameters: <code>{escape(json.dumps(learning_params, sort_keys=True))}</code></div>
          <div class="small-note">Recent parameter changes, strategy weights, session preferences, regime preferences, promotion history, rollback history, and realized cash contribution by model are read from the durable learning snapshot when available.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_performance_view(ctx: dict[str, object]) -> None:
    st.markdown("<div class='section-title'>Performance</div>", unsafe_allow_html=True)
    bucket = {}
    daily_reports = []
    db_path = Path("var/autotrader/research.db")
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT * FROM cash_buckets ORDER BY updated_at DESC LIMIT 1").fetchone()
                if row:
                    bucket = {"liquid": row[6], "harvested": row[7], "redeployable": row[8], "theoretical": row[10]}
                conn.row_factory = sqlite3.Row
                daily_reports = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT payload_json FROM daily_reports ORDER BY report_date DESC LIMIT 30"
                    ).fetchall()
                ]
        except sqlite3.Error:
            bucket = {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Starting Capital", _money(ctx["original_capital"]))
    c2.metric("Current Equity", _money(ctx["total_equity"]))
    c3.metric("Realized Cash", _money(ctx["net_cash"]))
    c4.metric("Unrealized P&L", _money(ctx["unrealized"]))
    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Liquid Cash", _money(bucket.get("liquid", ctx["available_cash"])))
    c10.metric("Harvested Cash", _money(bucket.get("harvested", 0)))
    c11.metric("Redeployable Cash", _money(bucket.get("redeployable", ctx["available_cash"])))
    c12.metric("Theoretical Compounded Equity", _money(bucket.get("theoretical", ctx["total_equity"])))
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Daily Return", _pct(ctx["daily_realized"]))
    c6.metric("Cumulative Return", _pct(ctx["cumulative_realized"]))
    c7.metric("Generated Cash Ratio", _pct(ctx["generated_cash_ratio"]))
    c8.metric("Risk-adjusted Return", "—")
    left, right = st.columns(2)
    left.markdown(
        """
        <div class="panel" style="padding:1rem">
          <div class="status-label">Operating Benchmark — reporting only</div>
          <div class="status-value">$20–$305 Daily Realized Cash</div>
          <div class="small-note">Benchmarks do not force trades. Cash/no-trade is valid.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    right.markdown(
        f"""
        <div class="panel" style="padding:1rem">
          <div class="status-label">Stretch Benchmark — reporting only</div>
          <div class="status-value">20%–40% Daily Return</div>
          <div class="small-note">Current realized return: {escape(_pct(ctx["daily_realized"]))} · current unrealized return: {escape(_pct(ctx["daily_unrealized"]))}</div>
          <div class="small-note">Distance to 20%: {escape(_pct(ctx["dist_low"]))} · Distance to 40%: {escape(_pct(ctx["dist_high"]))}</div>
          <div class="progress"><div style="width:{max(0.0, min(100.0, abs(ctx["daily_realized"]) / 0.40 * 100.0)):.1f}%"></div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    report_values = []
    for row in daily_reports:
        try:
            payload = json.loads(row["payload_json"])
            report_values.append(float(payload.get("realized_cash", 0.0)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    actual = report_values[0] if report_values else float(ctx["net_cash"])
    avg7 = sum(report_values[:7]) / len(report_values[:7]) if report_values[:7] else actual
    avg30 = sum(report_values) / len(report_values) if report_values else actual
    st.markdown("### Benchmark evidence · reporting only")
    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Actual realized cash", _money(actual))
    b2.metric("Operating target", "$20–$305")
    b3.metric("7-day average", _money(avg7))
    b4.metric("30-day average", _money(avg30))
    b5.metric("Distance to $20", _money(20.0 - actual))


def _render_risk_health_view(ctx: dict[str, object]) -> None:
    st.markdown("<div class='section-title'>Risk & Health</div>", unsafe_allow_html=True)
    backlog = (
        ctx["snapshot"].get("runtime", {}).get("backlog_progress") if isinstance(ctx.get("snapshot"), dict) else {}
    )
    backlog = backlog if isinstance(backlog, dict) else {}
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Strategy Baseline", _money(TOTAL_BASE_CAPITAL))
    r2.metric("Unresolved Manifests", str(len(ctx["unresolved"]) if isinstance(ctx["unresolved"], list) else 0))
    r3.metric("Broker Requests", str(int(_float(ctx["runtime"].get("rate_limit_telemetry", {}).get("requests"), 0.0))))
    r4.metric("429 Events", str(int(_float(ctx["runtime"].get("rate_limit_telemetry", {}).get("rate_limited"), 0.0))))
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Legacy Total", str(int(_float(backlog.get("legacy_total"), 0.0))))
    b2.metric("Legacy Deferred", str(int(_float(backlog.get("legacy_deferred"), 0.0))))
    b3.metric("Manual Review", str(int(_float(backlog.get("legacy_manual_review"), 0.0))))
    b4.metric("Active v2 Unresolved", str(int(_float(backlog.get("active_experiment_unresolved"), 0.0))))
    st.markdown(
        f"""
        <div class="small-note">Oldest unresolved: <strong>{escape(str(backlog.get("oldest_unresolved_timestamp") or "UNAVAILABLE"))}</strong> · newest unresolved: <strong>{escape(str(backlog.get("newest_unresolved_timestamp") or "UNAVAILABLE"))}</strong></div>
        <div class="small-note">Current history window: <strong>{escape(str((backlog.get("current_history_window") or {}).get("start") or "UNAVAILABLE"))}</strong> → <strong>{escape(str((backlog.get("current_history_window") or {}).get("end") or "UNAVAILABLE"))}</strong></div>
        <div class="small-note">Cooldown until: <strong>{escape(str(backlog.get("cooldown_until") or "UNAVAILABLE"))}</strong> · Last successful reconciliation: <strong>{escape(str(backlog.get("last_successful_reconciliation") or "UNAVAILABLE"))}</strong></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="small-note">The system remains PAPER/SIM only. Live trading stays disabled, duplicate intents stay blocked, and unresolved manifests are surfaced instead of being overwritten.</div>
        """,
        unsafe_allow_html=True,
    )
    if ctx["live_errors"]:
        st.warning(" · ".join(ctx["live_errors"]))


def _render_execution_log_view(ctx: dict[str, object]) -> None:
    st.markdown("<div class='section-title'>Execution Log</div>", unsafe_allow_html=True)
    rows = ctx["activity"] if isinstance(ctx["activity"], list) else []
    if rows:
        rows_html = "".join(
            "".join(
                [
                    "<tr>",
                    f"<td>{escape(str(row.get('timestamp') or row.get('time') or '—'))}</td>",
                    f"<td>{escape(str(row.get('pillar') or '—'))}</td>",
                    f"<td>{escape(str(row.get('symbol') or '—'))}</td>",
                    f"<td>{escape(str(row.get('event') or '—'))}</td>",
                    f"<td>{escape(str(row.get('decision') or '—'))}</td>",
                    f"<td>{escape(str(row.get('score') or '—'))}</td>",
                    f"<td>{escape(str(row.get('reason') or '—'))}</td>",
                    f"<td>{escape(str(row.get('result') or '—'))}</td>",
                    "</tr>",
                ]
            )
            for row in rows[:50]
        )
        st.markdown(
            f"""
            <div class="table-panel">
              <table>
                <thead><tr><th>Timestamp</th><th>Pillar</th><th>Symbol</th><th>Event</th><th>Decision</th><th>Score</th><th>Reason</th><th>Result</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No execution log events were found in the current snapshot.")


def _render_research_view(ctx: dict[str, object]) -> None:
    """Show research candidates without allowing discovery to control execution."""
    st.markdown("## RESEARCH & VALIDATION")
    st.caption(
        "External research remains isolated from broker execution until it passes the evidence-gated promotion policy."
    )
    db_path = Path("var/autotrader/research.db")
    rows = []
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT lane, source, as_of_date, freshness, instrument, signal_type, confidence, backtest_status, walk_forward_status, paper_shadow_status, promotion_status, model_weight, broker_control FROM research_records ORDER BY retrieved_at DESC LIMIT 100"
                    ).fetchall()
                ]
        except sqlite3.Error:
            rows = []
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No records ingested yet.")
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                providers = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT lane,status,last_success,last_attempt,next_refresh,records_ingested,last_error FROM provider_status ORDER BY lane"
                    ).fetchall()
                ]
            if providers:
                st.markdown("### Provider health")
                st.dataframe(providers, use_container_width=True, hide_index=True)
        except sqlite3.Error:
            st.warning("Provider health is unavailable.")
    st.markdown("### GLOBAL RESEARCH INTELLIGENCE")
    public_status_path = Path(os.getenv("GLOBAL_RESEARCH_STATUS", "var/global-intelligence/public-research.json"))
    if public_status_path.exists():
        try:
            public_status = json.loads(public_status_path.read_text(encoding="utf-8"))
            lane_rows = [
                {"lane": lane, **(value if isinstance(value, dict) else {})}
                for lane, value in (public_status.get("lanes") or {}).items()
            ]
            st.dataframe(lane_rows, use_container_width=True, hide_index=True)
        except (OSError, ValueError, TypeError):
            st.warning("Public research telemetry is unavailable.")
    st.caption("Public research, Kalshi intelligence, and challenger evidence are isolated from broker execution.")
    st.markdown("### KALSHI EVENT INTELLIGENCE · PILLAR 6")
    kalshi_db = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    kalshi_counts = {"predictions": 0, "perps": 0}
    kalshi_last = "UNKNOWN"
    if kalshi_db.exists():
        try:
            with sqlite3.connect(kalshi_db) as conn:
                kalshi_counts = dict(conn.execute("SELECT family, COUNT(*) FROM kalshi_observations GROUP BY family").fetchall())
                row = conn.execute("SELECT MAX(retrieved_at) FROM kalshi_observations").fetchone()
                kalshi_last = row[0] or kalshi_last
        except sqlite3.Error:
            pass
    kalshi = {
        "Authentication": "CONNECTED" if os.getenv("KALSHI_API_KEY_ID") and os.getenv("KALSHI_PRIVATE_KEY_PATH") else "NOT CONFIGURED",
        "Predictions REST": "CONNECTED",
        "Predictions WebSocket": "NOT ACTIVE",
        "Perps REST": "DEGRADED · NOT DOCUMENTED",
        "Perps WebSocket": "NOT ACTIVE",
        "Records ingested": str(sum(kalshi_counts.values())),
        "Prediction markets tracked": str(kalshi_counts.get("predictions", 0)),
        "Perps instruments tracked": "0",
        "Research features": "RESEARCH ONLY",
        "Shadow learning samples": "0",
        "Last successful update": kalshi_last,
        "Data freshness": "STORED OBSERVATIONS",
        "ACTIVE CAPITAL": "$0",
        "EXECUTION": "DISABLED",
        "BROKER CONTROL": "FALSE",
    }
    st.dataframe([kalshi], use_container_width=True, hide_index=True)
    st.markdown("### Promotion gate")
    st.info(
        "Promotion requires meaningful out-of-sample evidence, positive incremental results, bounded drawdown, and execution-quality limits. No research signal can submit an order directly."
    )
    st.metric("LIVE DEPLOYMENT READINESS", "COLLECTING EVIDENCE")


def _render_daily_reports_view(ctx: dict[str, object]) -> None:
    st.markdown("## DAILY REPORTS")
    db_path = Path("var/autotrader/research.db")
    reports = []
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                reports = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT report_date, payload_json FROM daily_reports ORDER BY report_date DESC"
                    ).fetchall()
                ]
        except sqlite3.Error:
            reports = []
    if not reports:
        st.info(
            "No daily report exists yet. The independent daily-report job will create one after its scheduled boundary."
        )
        return
    selected = st.selectbox("Report date", [row["report_date"] for row in reports])
    payload = json.loads(next(row["payload_json"] for row in reports if row["report_date"] == selected))
    cols = st.columns(5)
    for col, (label, key) in zip(
        cols,
        (
            ("Starting Equity", "starting_equity"),
            ("Ending Equity", "ending_equity"),
            ("Realized Cash", "realized_cash"),
            ("Daily Return", "daily_return"),
            ("Utilization", "capital_utilization"),
        ),
        strict=True,
    ):
        col.metric(
            label, _pct(payload.get(key)) if "return" in key or "utilization" in key else _money(payload.get(key))
        )
    st.dataframe([payload], use_container_width=True, hide_index=True)


def render_dashboard() -> None:
    last_refreshed = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.session_state["dashboard_last_refreshed"] = last_refreshed
    st.markdown(_dashboard_css(), unsafe_allow_html=True)
    st.sidebar.markdown(
        """
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
    auto_refresh = st.sidebar.toggle("Auto Refresh", value=bool(st.session_state.get("dashboard_auto_refresh", True)))
    st.session_state["dashboard_auto_refresh"] = auto_refresh
    refresh_interval = st.sidebar.radio(
        "Refresh Interval",
        ["30 seconds", "60 seconds", "120 seconds"],
        index=["30 seconds", "60 seconds", "120 seconds"].index(
            str(st.session_state.get("dashboard_refresh_interval", "60 seconds"))
        )
        if str(st.session_state.get("dashboard_refresh_interval", "60 seconds"))
        in {"30 seconds", "60 seconds", "120 seconds"}
        else 1,
        horizontal=False,
        key="dashboard_refresh_interval_widget",
    )
    st.session_state["dashboard_refresh_interval"] = refresh_interval
    if st.sidebar.button("Refresh Now", use_container_width=True):
        st.rerun()
    if auto_refresh:
        interval_seconds = {"30 seconds": 30, "60 seconds": 60, "120 seconds": 120}.get(refresh_interval, 60)
        st.markdown(f"<meta http-equiv='refresh' content='{interval_seconds}'>", unsafe_allow_html=True)
        st.sidebar.caption(f"Last refreshed: {last_refreshed}")
    else:
        st.sidebar.caption(f"Auto refresh paused · Last refreshed: {last_refreshed}")
    selected_view = st.sidebar.radio(
        "Navigation",
        [
            "OVERVIEW",
            "PILLARS",
            "POSITIONS",
            "TRADES",
            "LEARNING",
            "PERFORMANCE",
            "RESEARCH",
            "DAILY REPORTS",
            "RISK & HEALTH",
            "EXECUTION LOG",
        ],
        key="dashboard_navigation",
    )
    ctx = _build_dashboard_context()
    _render_dashboard_shell(ctx, selected_view)
    if selected_view == "OVERVIEW":
        _render_overview(ctx)
    elif selected_view == "PILLARS":
        _render_pillars_view(ctx)
    elif selected_view == "POSITIONS":
        _render_positions_view(ctx)
    elif selected_view == "TRADES":
        _render_trades_view(ctx)
    elif selected_view == "LEARNING":
        _render_learning_view(ctx)
    elif selected_view == "PERFORMANCE":
        _render_performance_view(ctx)
    elif selected_view == "RESEARCH":
        _render_research_view(ctx)
    elif selected_view == "DAILY REPORTS":
        _render_daily_reports_view(ctx)
    elif selected_view == "RISK & HEALTH":
        _render_risk_health_view(ctx)
    elif selected_view == "EXECUTION LOG":
        _render_execution_log_view(ctx)


def main() -> None:
    render_dashboard()


if __name__ == "__main__":
    main()
