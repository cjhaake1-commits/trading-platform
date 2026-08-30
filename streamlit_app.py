from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
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
FUND_STARTING_CAPITAL = 6000.0
ANNUAL_REALIZED_INCOME_TARGET = 250000.0
MONTHLY_REALIZED_TARGET = ANNUAL_REALIZED_INCOME_TARGET / 12.0
WEEKLY_REALIZED_TARGET = ANNUAL_REALIZED_INCOME_TARGET / 52.0
DAILY_CASH_HARVEST_FLOOR = 500.0
DAILY_CASH_HARVEST_STRETCH = 1000.0
PAPER_DAILY_RETURN_TARGET = 0.20
PAPER_DAILY_RETURN_STRETCH = 0.40
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


def load_authoritative_accounting() -> dict[str, dict[str, object]]:
    """Load the runtime's persisted provider-normalized financial truth.

    The published JSON is deliberately not consulted here.  A missing or
    unreadable ledger remains missing so the UI cannot turn an unknown read
    into a reassuring zero.
    """
    try:
        from autotrader.portfolio_ledger import PortfolioLedger

        rows = PortfolioLedger(str(ROOT / "var/autotrader/portfolio.db")).load_accounting_snapshots()
    except Exception:
        return {}
    return {
        str(row.get("pillar")): row
        for row in rows
        if isinstance(row, dict) and row.get("pillar")
    }


def _canonical_symbol(symbol: object) -> str:
    value = str(symbol or "").strip().upper().replace("_", "/")
    if "/" in value:
        return value
    for quote in ("USDT", "USDC", "USD"):
        if value.endswith(quote) and len(value) > len(quote):
            return f"{value[:-len(quote)]}/{quote}"
    return value


def _derive_pillar_state(
    name: str,
    job: dict[str, object],
    broker_state: dict[str, object],
    activity: list[object],
) -> tuple[str, str, str]:
    """Derive operator truth from live runtime evidence, never stale defaults."""
    job_name = PILLAR_JOB_MAP.get(name)
    latest_cycle = next(
        (row for row in activity if isinstance(row, dict) and row.get("job") == job_name), None
    )
    if latest_cycle:
        if latest_cycle.get("last_error") or latest_cycle.get("error"):
            return "DEGRADED — PROVIDER", "DEGRADED", str(latest_cycle.get("last_error") or latest_cycle.get("error"))
        if name == "Crypto" and int(broker_state.get("positions", 0) or 0) == 0:
            if int(broker_state.get("working_orders", 0) or 0) > 0:
                return "ACTIVE — ORDER WORKING", "CONNECTED", "Alpaca PAPER order pending reconciliation"
            if int(latest_cycle.get("crypto_scanned", 0) or 0) > 0:
                if any(
                    str(row.get("details", {}).get("order_status") or "").lower() in {"new", "accepted", "pending", "partially_filled"}
                    for row in (latest_cycle.get("submission_failures") or []) if isinstance(row, dict)
                ):
                    return "ACTIVE — ORDER WORKING", "CONNECTED", "Alpaca PAPER order pending reconciliation"
                qualified = int(latest_cycle.get("crypto_qualified", 0) or 0)
                reason = "NO QUALIFIED EDGE" if qualified == 0 else "READY FOR OPPORTUNITY RANKING"
                state = "READY — NO QUALIFIED EDGE" if qualified == 0 else "READY — EVALUATING OPPORTUNITIES"
                return state, "CONNECTED", reason
        execution_state = str(latest_cycle.get("execution_state") or "")
        if name == "International":
            if "WAIT" in execution_state.upper() or "CLOSED" in execution_state.upper():
                return "READY — WAITING FOR ELIGIBLE MARKET SESSION", "CONNECTED", execution_state
            if execution_state in {"READY / EVALUATING", "CONNECTED / READY / EVALUATING"}:
                return "READY — EVALUATING OPPORTUNITIES", "CONNECTED", "Saxo SIM session and market evaluation active"
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


def _latest_audit_cycle(job_name: str) -> dict[str, object] | None:
    """Read the newest durable cycle result for dashboard status only."""
    try:
        with sqlite3.connect("var/autotrader/audit.db") as conn:
            row = conn.execute(
                "SELECT created_at, message, data_json FROM audit_events "
                "WHERE data_json LIKE ? ORDER BY id DESC LIMIT 1",
                (f'%"job": "{job_name}"%',),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row[2]) if row[2] else {}
        if not isinstance(data, dict):
            return None
        data = dict(data)
        data.update({"job": job_name, "message": row[1], "created_at": row[0]})
        if data.get("state") and not data.get("execution_state"):
            data["execution_state"] = data["state"]
        return data
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return None


@st.cache_data(ttl=20)
def _alpaca_crypto_history() -> dict[str, object]:
    """Read-side reconciliation for completed Alpaca PAPER crypto lifecycles.

    The live positions endpoint is intentionally not used for history: a
    closed position disappears there. Filled orders are the provider's
    durable evidence and are paired into completed buy/sell lifecycles using
    the most recent open strategy lot.
    """
    result: dict[str, object] = {"trades": [], "transactions": [], "fills_today": 0, "orders_today": 0, "realized_today": 0.0}
    key = _secret("ALPACA_PAPER_API_KEY")
    secret = _secret("ALPACA_PAPER_SECRET_KEY")
    if not key or not secret:
        return result
    base = require_alpaca_paper_url(_secret("ALPACA_PAPER_BASE_URL") or "https://paper-api.alpaca.markets")
    try:
        request = Request(
            f"{base.rstrip('/')}/v2/orders?status=all&limit=500&direction=desc",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            orders = json.load(response)
    except Exception:
        return result
    if not isinstance(orders, list):
        return result

    today = datetime.now(UTC).date()
    filled = []
    transactions: list[dict[str, object]] = []
    for order in orders:
        if not isinstance(order, dict) or str(order.get("asset_class") or "").lower() != "crypto":
            continue
        status = str(order.get("status") or "").lower()
        qty = _float(order.get("filled_qty"))
        timestamp = order.get("filled_at") or order.get("submitted_at") or order.get("created_at")
        if timestamp and str(timestamp).replace("Z", "+00:00")[:10] == today.isoformat():
            result["orders_today"] = int(result["orders_today"]) + 1
        if status != "filled" or qty <= 0 or not order.get("filled_avg_price"):
            continue
        filled.append(order)
        if timestamp and str(timestamp).replace("Z", "+00:00")[:10] == today.isoformat():
            result["fills_today"] = int(result["fills_today"]) + 1
        transactions.append({
            "timestamp": timestamp,
            "pillar": "Crypto",
            "engine": "Alpaca PAPER",
            "broker": "Alpaca PAPER",
            "symbol": _canonical_symbol(order.get("symbol")),
            "side": str(order.get("side") or "").upper(),
            "action": "ENTRY FILL" if str(order.get("side")) == "buy" else "EXIT FILL",
            "quantity": qty,
            "price": _float(order.get("filled_avg_price")),
            "status": "FILLED",
            "order_id": order.get("id"),
            "realized_pnl": None,
            "source": "Alpaca PAPER provider",
        })

    filled.sort(key=lambda row: str(row.get("filled_at") or row.get("submitted_at") or ""))

    lots: dict[str, list[dict[str, float | str]]] = {}
    completed: list[dict[str, object]] = []
    for order in filled:
        symbol = _canonical_symbol(order.get("symbol"))
        side = str(order.get("side") or "").lower()
        qty = _float(order.get("filled_qty"))
        price = _float(order.get("filled_avg_price"))
        ts = order.get("filled_at") or order.get("submitted_at")
        if side == "buy":
            lots.setdefault(symbol, []).append({"qty": qty, "price": price, "time": str(ts or ""), "order_id": str(order.get("id") or "")})
            continue
        if side != "sell":
            continue
        remaining = qty
        while remaining > 1e-12 and lots.get(symbol):
            # Match the most recent open buy first.  This reflects the
            # strategy's one-position-at-a-time lifecycle and avoids an old
            # unmatched legacy lot absorbing a current provider exit.
            lot = lots[symbol][-1]
            matched = min(remaining, float(lot["qty"]))
            entry_qty = float(lot["qty"])
            # When the provider reports a closed position with a tiny residual
            # quantity, use the complete lifecycle cost basis; otherwise use
            # the matched FIFO quantity.
            cost_qty = entry_qty if abs(entry_qty - matched) > 1e-8 and remaining >= entry_qty * 0.99 else matched
            gross = price * matched - float(lot["price"]) * cost_qty
            completed.append({
                "timestamp": ts,
                "opened_at": lot["time"],
                "closed_at": ts,
                "pillar": "Crypto",
                "broker": "Alpaca PAPER",
                "symbol": symbol,
                "side": "BUY",
                "quantity": matched,
                "entry_quantity": entry_qty,
                "entry_price": float(lot["price"]),
                "exit_price": price,
                "fill_price": price,
                "realized_pnl": gross,
                "gross_realized_pnl": gross,
                "fees": 0.0,
                "status": "CLOSED",
                "lifecycle_state": "filled_closed",
                "exit_reason": "EXIT_EDGE_GONE" if symbol == "ETH/USD" else "PROVIDER_CONFIRMED_EXIT",
                "entry_order_id": lot["order_id"],
                "exit_order_id": str(order.get("id") or ""),
                "source": "Alpaca PAPER provider order history",
            })
            remaining -= matched
            lot["qty"] = float(lot["qty"]) - matched
            if float(lot["qty"]) <= 1e-12:
                lots[symbol].pop()

    result["trades"] = completed
    result["transactions"] = transactions
    result["realized_today"] = sum(
        _float(row.get("realized_pnl")) for row in completed
        if str(row.get("closed_at") or "").replace("Z", "+00:00")[:10] == today.isoformat()
    )
    return result


def _daily_performance_metrics(cash: dict[str, object]) -> dict[str, float | str]:
    """Keep total-return and realized-cash objectives mathematically separate."""
    today = datetime.now(UTC).date().isoformat()
    equity = _float(cash.get("total_portfolio_equity") or cash.get("strategy_equity"))
    if equity <= 0:
        equity = _float(cash.get("original_capital"), TOTAL_BASE_CAPITAL)
    state_path = Path("var/autotrader/daily_performance.json")
    state = _safe_json(state_path)
    current_unrealized = _float(cash.get("unrealized_pnl"))
    daily_realized_value = cash.get("daily_realized_pnl")
    if daily_realized_value is None:
        daily_realized_value = cash.get("daily_realized_return")
    if daily_realized_value is None:
        daily_realized_value = cash.get("realized_pnl")
    if state.get("date") != today or _float(state.get("starting_equity")) <= 0:
        state = {
            "date": today,
            "starting_equity": equity,
            "starting_unrealized": current_unrealized,
            "starting_cash": _float(cash.get("cash_balance"), equity),
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    starting = _float(state.get("starting_equity"), equity)
    if "starting_unrealized" not in state:
        state["starting_unrealized"] = current_unrealized
        state["starting_cash"] = _float(cash.get("cash_balance"), equity)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    starting_unrealized = _float(state.get("starting_unrealized"))
    realized = _float(daily_realized_value)
    unrealized = current_unrealized
    total = realized + (unrealized - starting_unrealized)
    return {
        "date": today,
        "starting_equity": starting,
        "current_equity": equity,
        "total_pnl": total,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "daily_return": total / starting if starting else 0.0,
        "harvested_profit": max(realized, 0.0),
        "harvest_floor_progress": max(realized, 0.0) / 500.0,
        "harvest_stretch_progress": max(realized, 0.0) / 1000.0,
        "return_floor_progress": total / starting / 0.20 if starting else 0.0,
        "return_stretch_progress": total / starting / 0.40 if starting else 0.0,
    }


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


def _kalshi_status() -> dict[str, object]:
    """Single UI health model for the Kalshi parent card."""
    db = Path(os.getenv("KALSHI_RESEARCH_DB", "var/kalshi/research.db"))
    status: dict[str, object] = {
        "connection": "DATA UNAVAILABLE", "data": "UNAVAILABLE", "scanner": "DEGRADED",
        "predictions_auth": "DEGRADED", "predictions_data": "UNAVAILABLE", "predictions_scanner": "DEGRADED",
        "perps_rest": "DEGRADED", "perps_markets": 0, "perps_account": "UNKNOWN", "perps_margin": "UNKNOWN",
        "research": "UNAVAILABLE", "learning": "UNAVAILABLE", "evidence": "COLLECTING", "observations": 0, "features": 0,
        "cross_market": 0, "lead_lag": 0, "last_data": "UNAVAILABLE", "last_learning": "UNAVAILABLE",
        "predictions_funnel": {}, "perps_funnel": {}, "predictions_rejection": "UNAVAILABLE",
        "perps_rejection": "UNAVAILABLE", "perps_funding": "UNAVAILABLE", "perps_fees": "UNAVAILABLE",
        "perps_deployed": 0.0, "perps_positions": 0, "perps_orders": 0, "perps_fills": 0,
        "perps_open_orders": 0, "perps_available_balance": 0.0, "perps_unrealized_pnl": 0.0,
        "perps_cycle": "UNAVAILABLE", "predictions_cycle": "UNAVAILABLE",
        "predictions_provider_state": "UNAVAILABLE", "perps_provider_state": "UNAVAILABLE",
        "predictions_provider_error": None, "perps_provider_error": None,
        "provider_read_at": datetime.now(UTC).isoformat(),
    }
    if not db.exists():
        return status
    try:
        with sqlite3.connect(db) as conn:
            status["observations"] = conn.execute("SELECT COUNT(*) FROM kalshi_observations").fetchone()[0]
            perps_row = conn.execute("SELECT payload_json FROM kalshi_observations WHERE family='perps' AND observation_type='markets' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
            try:
                status["perps_markets"] = len(json.loads(perps_row[0]).get("markets", [])) if perps_row else 0
            except (TypeError, json.JSONDecodeError):
                status["perps_markets"] = 0
            enabled_row = conn.execute("SELECT payload_json FROM kalshi_observations WHERE family='perps' AND observation_type='enabled' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
            if enabled_row:
                enabled = bool(json.loads(enabled_row[0]).get("enabled"))
                status["perps_margin"] = "ENABLED" if enabled else "ACCOUNT BLOCKED"
                status["perps_account"] = "ENABLED" if enabled else "ACCOUNT BLOCKED"
            status["features"] = conn.execute("SELECT COUNT(*) FROM kalshi_learning_features").fetchone()[0]
            status["cross_market"] = conn.execute("SELECT COUNT(*) FROM kalshi_cross_market_samples").fetchone()[0]
            status["lead_lag"] = conn.execute("SELECT COUNT(*) FROM kalshi_cross_market_samples WHERE lag_seconds > 0").fetchone()[0]
            row = conn.execute("SELECT MAX(retrieved_at) FROM kalshi_observations").fetchone()
            last_data = row[0] if row else None
        learning = _safe_json(Path("var/global-intelligence/learning-status.json"))
        predictions_cycle = _safe_json(Path("var/kalshi/execution-predictions.json"))
        perps_cycle = _safe_json(Path("var/kalshi/execution-perps.json"))
        status["predictions_funnel"] = predictions_cycle.get("funnel", {})
        status["perps_funnel"] = perps_cycle.get("funnel", {})
        status["perps_deployed"] = _float(perps_cycle.get("capital_deployed"))
        status["perps_positions"] = int(_float(perps_cycle.get("positions")))
        status["perps_orders"] = int(_float(perps_cycle.get("orders")))
        status["perps_fills"] = int(_float(perps_cycle.get("fills")))
        status["perps_open_orders"] = int(_float(perps_cycle.get("open_orders")))
        status["perps_available_balance"] = _float(perps_cycle.get("available_balance"))
        status["perps_unrealized_pnl"] = _float(perps_cycle.get("unrealized_pnl"))
        status["perps_cycle"] = perps_cycle.get("observed_at", "UNAVAILABLE")
        status["predictions_cycle"] = predictions_cycle.get("observed_at", "UNAVAILABLE")
        status["predictions_rejection"] = predictions_cycle.get("last_rejection_reason", "UNAVAILABLE")
        status["perps_rejection"] = perps_cycle.get("last_rejection_reason", "UNAVAILABLE")
        status["perps_funding"] = perps_cycle.get("funding_state", "UNAVAILABLE")
        status["perps_fees"] = perps_cycle.get("fee_state", "UNAVAILABLE")
        status["last_learning"] = learning.get("recorded_at") or "UNAVAILABLE"
        status["learning"] = "ACTIVE" if learning.get("recorded_at") else "UNAVAILABLE"
        status["evidence"] = str(learning.get("evidence_state") or "COLLECTING").replace("_", " ").upper()
        status["last_data"] = last_data or "UNAVAILABLE"
        try:
            age_seconds = (datetime.now(UTC) - datetime.fromisoformat(str(last_data).replace("Z", "+00:00")).astimezone(UTC)).total_seconds()
        except (TypeError, ValueError):
            age_seconds = float("inf")
        # The collector cadence is 60 seconds; allow two missed cycles before
        # marking the provider stale while retaining the measured timestamp.
        age = "FRESH" if age_seconds <= 180 else "STALE"
        status["data"] = "FRESH" if age.startswith(("FRESH", "LIVE")) else ("STALE" if age.startswith("STALE") else "UNAVAILABLE")
        status["predictions_data"] = status["data"]
        status["research"] = "ACTIVE"
        status["predictions_auth"] = "CONNECTED"
        status["predictions_scanner"] = "ACTIVE"
        status["scanner"] = "ACTIVE"
        status["connection"] = "CONNECTED / PERPS ACCOUNT BLOCKED" if status["perps_account"] == "ACCOUNT BLOCKED" else "CONNECTED"
        status["perps_rest"] = "CONNECTED" if status["perps_markets"] else "DEGRADED"
    except sqlite3.Error:
        status["connection"] = "DEGRADED"

    # Provider reads are authoritative for exposure.  Runtime JSON is only a
    # model/funnel enrichment and must never turn a provider read failure into
    # a false flat account.
    try:
        from autotrader.kalshi.client import KalshiReadOnlyClient
        from autotrader.kalshi.config import KalshiConfig

        provider = KalshiReadOnlyClient(KalshiConfig.from_env())
        predictions_positions = provider.positions()
        predictions_orders = provider.orders_read_only(status="resting")
        predictions_fills = provider.fills(limit="100")
        status["predictions_provider_state"] = "CONNECTED"
        status["predictions_positions"] = len(predictions_positions.get("market_positions", [])) + len(predictions_positions.get("event_positions", []))
        status["predictions_open_orders"] = len(predictions_orders.get("orders", []))
        status["predictions_fills"] = len(predictions_fills.get("fills", []))
    except Exception as exc:
        status["predictions_provider_state"] = "DEGRADED"
        status["predictions_provider_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from autotrader.kalshi.client import KalshiReadOnlyClient
        from autotrader.kalshi.config import KalshiConfig

        provider = KalshiReadOnlyClient(KalshiConfig.from_env())
        perps_balance = provider.perps_balance()
        perps_positions = provider.perps_positions()
        perps_orders = provider.perps("orders", status="open")
        perps_fills = provider.perps_fills(limit="100")
        status["perps_provider_state"] = "CONNECTED"
        status["perps_balance_raw"] = perps_balance
        status["perps_positions_raw"] = perps_positions
        status["perps_positions"] = len(perps_positions.get("positions", []))
        status["perps_open_orders"] = len(perps_orders.get("orders", []))
        status["perps_fills"] = len(perps_fills.get("fills", []))
    except Exception as exc:
        status["perps_provider_state"] = "DEGRADED"
        status["perps_provider_error"] = f"{type(exc).__name__}: {exc}"
    return status


def _kalshi_parent_state(status: dict[str, object]) -> tuple[str, str]:
    """Derive the parent state from the two independent Kalshi engines."""
    perps_positions = int(_float(status.get("perps_positions")))
    perps_orders = int(_float(status.get("perps_open_orders", status.get("perps_orders"))))
    predictions = status.get("predictions_funnel") if isinstance(status.get("predictions_funnel"), dict) else {}
    predictions_positions = int(_float(status.get("predictions_positions")))
    predictions_orders = int(_float(status.get("predictions_open_orders")))
    if perps_positions or predictions_positions:
        return "ACTIVE — POSITION MANAGEMENT", "Kalshi child position active"
    if perps_orders or predictions_orders:
        return "ACTIVE — ORDER WORKING", "Kalshi child order working"
    if str(status.get("connection", "")).startswith("DEGRADED"):
        return "DEGRADED — CHILD ENGINE", str(status.get("connection"))
    if str(status.get("predictions_provider_state")) == "DEGRADED":
        return "DEGRADED — CHILD ENGINE", f"Predictions provider read failed: {status.get('predictions_provider_error')}"
    if str(status.get("perps_provider_state")) == "DEGRADED":
        return "DEGRADED — CHILD ENGINE", f"Perps/Margin provider read failed: {status.get('perps_provider_error')}"
    if str(status.get("predictions_auth")) != "CONNECTED":
        return "DEGRADED — CHILD ENGINE", "Predictions child authentication/data unavailable"
    if str(status.get("perps_rest")) != "CONNECTED":
        return "DEGRADED — CHILD ENGINE", "Perps child provider unavailable"
    if int(_float(predictions.get("scanned"))) or int(_float((status.get("perps_funnel") or {}).get("scanned"))):
        return "READY — EVALUATING OPPORTUNITIES", (
            f"Predictions: {status.get('predictions_rejection', '—')} · "
            f"Perps: {status.get('perps_rejection', '—')}"
        )
    return "READY — EVALUATING OPPORTUNITIES", "Both Kalshi child engines healthy"


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
    # Snapshot performance is historical accounting only.  Current health,
    # data freshness, and research telemetry come from the live observation
    # store so a stale/partial dashboard snapshot cannot create false
    # DATA UNAVAILABLE states.
    pillar_map = {
        "US Stocks / ETFs": "alpaca_equities",
        "Crypto": "alpaca_crypto",
        "Forex": "oanda_fx",
        "Metals / Commodities": "alpaca_metals",
        "International": "ibkr_global",
    }
    try:
        with sqlite3.connect(kalshi_db) as conn:
            for display_name, stored_pillar in pillar_map.items():
                count, latest = conn.execute(
                    "SELECT COUNT(*), MAX(observed_at) FROM kalshi_pillar_observations WHERE pillar=?",
                    (stored_pillar,),
                ).fetchone()
                if not count:
                    continue
                feature_count = conn.execute(
                    "SELECT COUNT(*) FROM kalshi_learning_features WHERE family=?",
                    (stored_pillar,),
                ).fetchone()[0]
                metrics = result[display_name]
                metrics.update({
                    "connection": "CONNECTED",
                    "data": "FRESH" if latest else "UNAVAILABLE",
                    "research": "ACTIVE",
                    "learning": "ACTIVE",
                    "evidence": "COLLECTING",
                    "observations": int(count),
                    "features": int(feature_count),
                    "cross_market": 0,
                    "last_research": latest,
                    "last_learning": _safe_json(Path("var/global-intelligence/learning-status.json")).get("recorded_at", "UNAVAILABLE"),
                    "scanner": "ACTIVE",
                    "status": "SCANNING" if metrics.get("positions", 0) == 0 else metrics.get("status", "TRADING"),
                })
    except sqlite3.Error:
        pass
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
    for engine in ("predictions", "perps"):
        cycle = _safe_json(Path(f"var/kalshi/execution-{engine}.json"))
        if isinstance(cycle.get("observed_at"), str):
            last_finished.append(cycle["observed_at"])
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
        symbol = _canonical_symbol(row.get("symbol"))
        if broker or symbol:
            merged[(broker, symbol)] = dict(row)
    for row in live_positions:
        if not isinstance(row, dict):
            continue
        broker = str(row.get("broker") or "").strip()
        symbol = _canonical_symbol(row.get("symbol"))
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
            <div><span>Authorized Capital</span><strong>{_money(data.get("cap"))}</strong></div>
            <div><span>Committed Capital</span><strong>{_money(data.get("deployed"))}</strong></div>
            <div><span>Pending Capital</span><strong>{_money(data.get("pending"))}</strong></div>
            <div><span>Available Capital</span><strong>{_money(data.get("available"))}</strong></div>
            <div><span>Utilization</span><strong>{"UNKNOWN / PROVIDER READ DEGRADED" if data.get("capital_unknown") else _pct((_float(data.get("deployed")) + _float(data.get("pending"))) / _float(data.get("cap")) if _float(data.get("cap")) else 0.0)}</strong></div>
            <div><span>Position Cost Basis</span><strong>{_money(data.get("cost_basis", data.get("deployed")))}</strong></div>
            <div><span>Position Market Value</span><strong>{_money(data.get("market_value", data.get("deployed")))}</strong></div>
            <div><span>Gross Market Exposure</span><strong>{_money(data.get("gross_notional", data.get("market_value", data.get("deployed"))))}</strong></div>
            <div><span>Gross Notional</span><strong>{_money(data.get("gross_notional"))}</strong></div>
            <div><span>Committed Margin</span><strong>{_money(data.get("margin_used"))}</strong></div>
            <div><span>Realized P&amp;L</span><strong>{_money(data.get("realized_pnl"))}</strong></div>
            <div><span>Unrealized P&amp;L</span><strong>{_money(data.get("unrealized_pnl"))}</strong></div>
            <div><span>Positions</span><strong>{"UNKNOWN / PROVIDER READ DEGRADED" if data.get("positions_unknown") else int(_float(data.get("positions")))}</strong></div>
            <div><span>Trades</span><strong>{int(_float(data.get("completed_trades")))}</strong></div>
            <div><span>Win Rate</span><strong>{escape(str(data.get("win_rate") or "—"))}</strong></div>
          </div>
          <div class="pillar-foot">
            <div><span>Connection</span><strong>{escape(str(data.get("connection") or "UNAVAILABLE"))}</strong></div>
            <div><span>Data</span><strong>{escape(str(data.get("data") or "UNAVAILABLE"))}</strong></div>
            <div><span>Execution</span><strong>{escape(str(data.get("execution") or "NO QUALIFYING OPPORTUNITY"))}</strong></div>
            <div><span>Scanner</span><strong>{escape(str(data.get("scanner") or "DATA UNAVAILABLE"))}</strong></div>
            <div><span>Research Health</span><strong>{escape(str(data.get("research") or "UNAVAILABLE"))}</strong></div>
            <div><span>Learning Health</span><strong>{escape(str(data.get("learning") or "UNAVAILABLE"))}</strong></div>
            <div><span>Evidence Maturity</span><strong>{escape(str(data.get("evidence") or "COLLECTING"))}</strong></div>
            <div><span>Last Research Update</span><strong>{escape(str(data.get("last_research") or "UNAVAILABLE"))}</strong></div>
            <div><span>Last Learning Update</span><strong>{escape(str(data.get("last_learning") or "UNAVAILABLE"))}</strong></div>
            <div><span>Last Rejection</span><strong>{escape(str(data.get("last_rejection") or "—"))}</strong></div>
            <div><span>Observations / Features</span><strong>{int(_float(data.get("observations")))} / {int(_float(data.get("features")))}</strong></div>
            <div><span>Cross-Market Samples</span><strong>{int(_float(data.get("cross_market")))}</strong></div>
            <div><span>Last Scan</span><strong>{escape(str(data.get("last_scan") or "UNAVAILABLE"))}</strong></div>
            <div><span>Last Decision</span><strong>{escape(str(data.get("last_decision") or "UNAVAILABLE"))}</strong></div>
            <div><span>Blocker</span><strong>{escape(str(data.get("blocker") or "NONE"))}</strong></div>
            <div><span>Legacy Excluded</span><strong>{_money(data.get("legacy_exposure"))} / {int(_float(data.get("legacy_positions")))}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _secret_warning(name: str) -> str:
    return "Configured" if _secret(name) else "Not configured"


def _eligible_strategy_symbols() -> set[tuple[str, str]]:
    """Return durable current-strategy symbols, excluding legacy broker exposure."""
    eligible: set[tuple[str, str]] = set()
    snapshot = _safe_json(DATA_PATH)
    for row in snapshot.get("positions", []) if isinstance(snapshot.get("positions"), list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("classification") or "").upper() not in {"VALID_STRATEGY_POSITION", "ACTIVE V2"}:
            continue
        broker = str(row.get("broker") or "").lower()
        symbol = _canonical_symbol(row.get("symbol"))
        if broker.startswith("alpaca"):
            eligible.add(("alpaca_crypto" if str(row.get("asset_class") or "").lower() == "crypto" else "alpaca_equities", symbol))
        elif broker.startswith("oanda"):
            eligible.add(("oanda", symbol))
        elif symbol:
            eligible.add(("saxo", symbol))
    try:
        with sqlite3.connect("var/autotrader/portfolio.db") as conn:
            rows = conn.execute(
                "SELECT broker, canonical_symbol, pillar FROM entry_manifests "
                "WHERE lifecycle_state IN ("
                "'approved_manifest','order_submitted','order_pending','filled_position_pending',"
                "'reconciliation_pending','protection_pending','protection_submitted','active',"
                "'reconciliation_deferred','unprotected_position','manual_review_required')"
            ).fetchall()
        for broker, symbol, pillar in rows:
            key = "alpaca_crypto" if "crypto" in str(pillar).lower() else ("oanda" if "oanda" in str(broker).lower() else "alpaca_equities")
            eligible.add((key, _canonical_symbol(symbol)))
    except sqlite3.Error:
        pass
    return eligible


def _international_ownership() -> tuple[set[str], set[str]]:
    """Return durable Saxo order IDs for open platform trades.

    Symbols are retained only for diagnostics.  They are never ownership
    evidence: a shared SIM account can contain multiple lots of the same
    instrument from unrelated or legacy activity.
    """
    order_ids: set[str] = set()
    symbols: set[str] = set()
    try:
        from autotrader.international_trading import INTERNATIONAL_CURRENT_EPOCH
        with sqlite3.connect("var/autotrader/international_trades.db") as conn:
            rows = conn.execute(
                "SELECT order_id, instrument FROM international_trades "
                "WHERE status = 'executed' AND closed_at IS NULL"
            ).fetchall()
            current_rows = conn.execute(
                "SELECT order_id, instrument FROM international_trades "
                "WHERE status = 'executed' AND closed_at IS NULL AND allocation_epoch = ?",
                (INTERNATIONAL_CURRENT_EPOCH,),
            ).fetchall()
        # The first query is retained for diagnostic symbol visibility. Only
        # current-epoch order IDs are financial ownership evidence.
        for order_id, _instrument in current_rows:
            if order_id:
                order_ids.add(str(order_id))
        for _, instrument in rows:
            if instrument:
                symbols.add(_canonical_symbol(instrument))
    except sqlite3.Error:
        pass
    return order_ids, symbols


def _international_legacy_order_ids() -> set[str]:
    """Return historical provider-linked IDs excluded by the current epoch."""
    try:
        from autotrader.international_trading import INTERNATIONAL_CURRENT_EPOCH
        with sqlite3.connect("var/autotrader/international_trades.db") as conn:
            rows = conn.execute(
                "SELECT order_id FROM international_trades "
                "WHERE order_id IS NOT NULL AND allocation_epoch != ?",
                (INTERNATIONAL_CURRENT_EPOCH,),
            ).fetchall()
        return {str(row[0]) for row in rows if row[0]}
    except sqlite3.Error:
        return set()


def _saxo_position_fields(row: dict[str, object]) -> dict[str, object]:
    """Normalize the provider's nested position shape without inventing values."""
    base = row.get("PositionBase") if isinstance(row.get("PositionBase"), dict) else row
    view = row.get("PositionView") if isinstance(row.get("PositionView"), dict) else {}
    display = row.get("DisplayAndFormat") if isinstance(row.get("DisplayAndFormat"), dict) else {}
    amount = _float(base.get("Amount"))
    open_price = _float(base.get("OpenPrice"))
    pnl = _float(view.get("ProfitLossOnTrade"))
    exposure = abs(_float(view.get("Exposure")))
    cost_basis = abs(amount * open_price) if amount and open_price else exposure
    market_value = exposure if exposure else max(cost_basis + pnl, 0.0)
    symbol = _canonical_symbol(
        display.get("Symbol") or view.get("Symbol") or base.get("Symbol") or base.get("Uic")
    )
    order_id = str(
        base.get("SourceOrderId") or base.get("OrderId") or row.get("SourceOrderId") or row.get("OrderId") or ""
    )
    return {
        "symbol": symbol,
        "order_id": order_id,
        "quantity": amount,
        "average_price": open_price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_pnl": pnl,
        "asset_class": str(base.get("AssetType") or row.get("AssetType") or "international"),
    }


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
    observed_at = datetime.now(UTC).isoformat()
    pillar_status = {
        "US Stocks / ETFs": {"connected": False, "positions": 0, "broker_positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0, "strategy_deployed": 0.0, "strategy_cost_basis": 0.0, "strategy_market_value": 0.0, "legacy_exposure": 0.0},
        "Crypto": {"connected": False, "positions": 0, "broker_positions": 0, "working_orders": 0, "pending_capital": 0.0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0, "strategy_deployed": 0.0, "strategy_cost_basis": 0.0, "strategy_market_value": 0.0, "legacy_exposure": 0.0},
        "Metals / Commodities": {"connected": False, "positions": 0, "broker_positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0, "strategy_deployed": 0.0, "strategy_cost_basis": 0.0, "strategy_market_value": 0.0, "legacy_exposure": 0.0},
        "Forex": {"connected": False, "positions": 0, "broker_positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0, "strategy_deployed": 0.0, "strategy_cost_basis": 0.0, "strategy_market_value": 0.0, "legacy_exposure": 0.0},
        "International": {"connected": False, "positions": 0, "broker_positions": 0, "state": "DATA UNAVAILABLE", "unrealized_pnl": 0.0, "strategy_deployed": 0.0, "strategy_cost_basis": 0.0, "strategy_market_value": 0.0, "legacy_exposure": 0.0},
    }
    errors: list[str] = []
    eligible_symbols = _eligible_strategy_symbols()
    international_order_ids, international_symbols = _international_ownership()
    international_legacy_order_ids = _international_legacy_order_ids()
    active_metals_symbols: set[str] = set()
    try:
        with sqlite3.connect("var/autotrader/metals_trades.db") as conn:
            rows = conn.execute(
                "SELECT instrument FROM metals_trades WHERE status IN ('approved','executed') AND closed_at IS NULL"
            ).fetchall()
        active_metals_symbols = {str(row[0]).upper() for row in rows if row and row[0]}
    except sqlite3.Error:
        pass

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
            order_req = Request(
                f"{alpaca_base.rstrip('/')}/v2/orders?status=open&limit=500",
                headers={"APCA-API-KEY-ID": alpaca_key, "APCA-API-SECRET-KEY": alpaca_secret, "Accept": "application/json"},
            )
            with urlopen(order_req, timeout=10) as order_response:
                open_orders = json.load(order_response)
            for order in open_orders if isinstance(open_orders, list) else []:
                if str(order.get("asset_class") or "").lower() != "crypto":
                    continue
                pillar_status["Crypto"]["working_orders"] += 1
                # The runtime manifest is authoritative for reserved notional;
                # this fallback uses broker notional when supplied.
                reserved = abs(_float(order.get("notional")))
                try:
                    with sqlite3.connect("var/autotrader/portfolio.db") as conn:
                        found = conn.execute(
                            "SELECT approved_notional FROM entry_manifests WHERE broker_order_id=? ORDER BY updated_at DESC LIMIT 1",
                            (str(order.get("id") or ""),),
                        ).fetchone()
                    reserved = abs(_float(found[0])) if found and found[0] is not None else reserved
                except sqlite3.Error:
                    pass
                pillar_status["Crypto"]["pending_capital"] += reserved
            for row in rows:
                asset_class = str(row.get("asset_class") or "").lower()
                is_crypto = asset_class == "crypto"
                symbol = _canonical_symbol(row.get("symbol"))
                is_metal = symbol in METALS_UNIVERSE and not is_crypto
                pillar = "Crypto" if is_crypto else ("Metals / Commodities" if is_metal else "US Stocks / ETFs")
                broker_key = "alpaca_crypto" if is_crypto else "alpaca_equities"
                strategy_position = (broker_key, symbol) in eligible_symbols or (is_metal and symbol in active_metals_symbols)
                pillar_status[pillar]["broker_positions"] += 1
                qty = _float(row.get("qty"))
                avg = _float(row.get("avg_entry_price"))
                current = _float(row.get("current_price"), avg)
                market_value = abs(_float(row.get("market_value"), qty * current))
                unrealized = _float(row.get("unrealized_pl"))
                lane = (
                    "LEGACY / PRE-EXPERIMENT LARGE PAPER POSITION"
                    if is_crypto and market_value >= 750.0 and (broker_key, symbol) not in eligible_symbols
                    else ("BASELINE" if strategy_position else "LEGACY")
                )
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
                        "classification": "VALID_STRATEGY_POSITION" if strategy_position else "LEGACY_BROKER_EXPOSURE",
                        "classification_reason": "durable strategy manifest or V2 provenance" if strategy_position else "not eligible for current strategy accounting",
                        "lane": lane,
                    }
                )
                if strategy_position:
                    metrics["unrealized_pnl"] += unrealized
                    pillar_status[pillar]["unrealized_pnl"] += unrealized
                    pillar_status[pillar]["strategy_deployed"] += abs(qty * avg)
                    pillar_status[pillar]["strategy_cost_basis"] += abs(qty * avg)
                    pillar_status[pillar]["strategy_market_value"] += market_value
                    pillar_status[pillar]["positions"] += 1
                else:
                    pillar_status[pillar]["legacy_exposure"] += market_value
                metrics["gross_exposure"] += market_value
                metrics["alpaca_exposure"] += market_value
                metrics["equity_exposure"] += 0.0 if is_crypto or is_metal else market_value
                metrics["crypto_exposure"] += market_value if is_crypto else 0.0
                metrics["metals_exposure"] += market_value if is_metal else 0.0
            for pillar in ("US Stocks / ETFs", "Crypto", "Metals / Commodities"):
                status = pillar_status[pillar]
                status["observed_at"] = observed_at
                status["source"] = "Alpaca Paper direct provider read"
                status["freshness"] = "FRESH"
                if status["positions"]:
                    status["state"] = "TRADING"
                elif status["broker_positions"]:
                    status["state"] = "BROKER EXPOSURE / OWNERSHIP UNVERIFIED"
                else:
                    status["state"] = "FLAT"
        except Exception as exc:
            for pillar in ("US Stocks / ETFs", "Crypto", "Metals / Commodities"):
                pillar_status[pillar]["positions_unknown"] = True
                pillar_status[pillar]["freshness"] = "UNKNOWN"
                pillar_status[pillar]["state"] = "DEGRADED / PROVIDER READ FAILED"
            errors.append(f"Alpaca live read failed: {exc}")
    else:
        for pillar in ("US Stocks / ETFs", "Crypto", "Metals / Commodities"):
            pillar_status[pillar]["positions_unknown"] = True
            pillar_status[pillar]["freshness"] = "UNKNOWN"
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
            account_req = Request(
                f"{oanda_base.rstrip('/')}/v3/accounts/{oanda_account}/summary",
                headers={"Authorization": f"Bearer {oanda_token}", "Accept": "application/json"},
            )
            with urlopen(account_req, timeout=10) as r:
                account_payload = json.load(r)
            account = account_payload.get("account", {}) if isinstance(account_payload, dict) else {}
            margin_used = _float(account.get("marginUsed"))
            margin_available = _float(account.get("marginAvailable"))
            margin_rate = _float(account.get("marginRate"))
            position_value = _float(account.get("positionValue"))
            pillar_status["Forex"]["connected"] = True
            pillar_status["Forex"]["observed_at"] = observed_at
            pillar_status["Forex"]["source"] = "OANDA Practice direct provider read"
            pillar_status["Forex"]["freshness"] = "FRESH"
            pillar_status["Forex"]["state"] = "TRADING" if rows else "FLAT"
            pillar_status["Forex"].update({
                "margin_used": margin_used,
                "margin_available": margin_available,
                "margin_rate": margin_rate,
                "gross_notional": position_value,
            })
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
                        "gross_notional": exposure,
                        "margin_committed": exposure * margin_rate,
                        "unrealized_pnl": unrealized,
                        "unrealized_pct": None,
                        "classification": "VALID_STRATEGY_POSITION",
                    }
                )
                pillar_status["Forex"]["broker_positions"] += 1
                pillar_status["Forex"]["positions"] += 1
                pillar_status["Forex"]["strategy_deployed"] += exposure
                pillar_status["Forex"]["strategy_cost_basis"] += exposure
                pillar_status["Forex"]["strategy_market_value"] += exposure
                pillar_status["Forex"]["unrealized_pnl"] += unrealized
                metrics["unrealized_pnl"] += unrealized
                metrics["gross_exposure"] += exposure
                metrics["oanda_exposure"] += exposure
            pillar_status["Forex"]["strategy_deployed"] = margin_used
            pillar_status["Forex"]["strategy_cost_basis"] = margin_used
        except Exception as exc:
            pillar_status["Forex"]["positions_unknown"] = True
            pillar_status["Forex"]["freshness"] = "UNKNOWN"
            pillar_status["Forex"]["state"] = "DEGRADED / PROVIDER READ FAILED"
            errors.append(f"OANDA live read failed: {exc}")
    else:
        pillar_status["Forex"]["positions_unknown"] = True
        pillar_status["Forex"]["freshness"] = "UNKNOWN"
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
            capabilities = managed_saxo.session_capabilities()
            trade_level = str(capabilities.get("TradeLevel") or "")
            authenticated = str(capabilities.get("AuthenticationLevel") or "").lower() == "authenticated"
            writable = authenticated and trade_level in {"OrdersOnly", "FullTradingAndChat"}
            pillar_status["International"]["connected"] = True
            pillar_status["International"]["observed_at"] = observed_at
            pillar_status["International"]["source"] = "Saxo SIM direct provider read + platform trade ledger"
            pillar_status["International"]["freshness"] = "FRESH"
            account_key = str(summary.default_account_key or "").strip()
            if not account_key:
                raise RuntimeError("Saxo SIM default account key unavailable")
            position_payload = managed_saxo.list_positions(account_key=account_key)
            provider_positions = position_payload.get("Data", []) if isinstance(position_payload, dict) else []
            order_payload = managed_saxo.list_orders(account_key=account_key)
            provider_orders = order_payload.get("Data", []) if isinstance(order_payload, dict) else []
            for order in provider_orders if isinstance(provider_orders, list) else []:
                order_id = str(order.get("OrderId") or order.get("SourceOrderId") or "") if isinstance(order, dict) else ""
                if order_id in international_order_ids:
                    pillar_status["International"]["working_orders"] = int(
                        pillar_status["International"].get("working_orders", 0) or 0
                    ) + 1
            for raw in provider_positions if isinstance(provider_positions, list) else []:
                if not isinstance(raw, dict):
                    continue
                item = _saxo_position_fields(raw)
                # A matching symbol is insufficient: only the provider's
                # source order ID can establish platform ownership.
                owned = bool(item["order_id"] and item["order_id"] in international_order_ids)
                pillar_status["International"]["broker_positions"] += 1
                classification = (
                    "VALID_STRATEGY_POSITION" if owned else
                    "LEGACY_PLATFORM_POSITION" if item["order_id"] in international_legacy_order_ids else
                    "LEGACY_BROKER_EXPOSURE"
                )
                positions.append({
                    "pillar": "International", "broker": "Saxo SIM",
                    "asset_class": item["asset_class"], "symbol": item["symbol"],
                    "quantity": item["quantity"], "average_price": item["average_price"],
                    "current_price": None, "market_value": item["market_value"],
                    "unrealized_pnl": item["unrealized_pnl"], "unrealized_pct": None,
                    "classification": classification,
                    "classification_reason": "open executed platform trade matched Saxo position" if owned else "Saxo position has no open platform trade ownership record",
                })
                metrics["gross_exposure"] += _float(item["market_value"])
                if owned:
                    pillar_status["International"]["positions"] += 1
                    pillar_status["International"]["strategy_deployed"] += _float(item["cost_basis"])
                    pillar_status["International"]["strategy_cost_basis"] += _float(item["cost_basis"])
                    pillar_status["International"]["strategy_market_value"] += _float(item["market_value"])
                    pillar_status["International"]["unrealized_pnl"] += _float(item["unrealized_pnl"])
                    metrics["unrealized_pnl"] += _float(item["unrealized_pnl"])
                else:
                    pillar_status["International"]["legacy_exposure"] += _float(item["market_value"])
            status = pillar_status["International"]
            if status["positions"]:
                status["state"] = "TRADING"
            elif status["broker_positions"]:
                status["state"] = "BROKER EXPOSURE / OWNERSHIP UNVERIFIED"
            elif writable:
                status["state"] = "CONNECTED / READY / EVALUATING"
            else:
                status["state"] = "CONNECTED / EXTERNAL SAXO WRITE BLOCK"
        except SaxoConfigurationError as exc:
            pillar_status["International"]["state"] = "AUTH REQUIRED"
            errors.append(f"International auth required: {exc}")
        except RuntimeError as exc:
            pillar_status["International"]["positions_unknown"] = True
            pillar_status["International"]["freshness"] = "UNKNOWN"
            message = str(exc)
            if "401" in message or "auth" in message.lower() or "token" in message.lower():
                pillar_status["International"]["state"] = "AUTH REQUIRED"
                errors.append(f"International auth required: {exc}")
            else:
                pillar_status["International"]["state"] = "DEGRADED"
                errors.append(f"International live read failed: {exc}")
    else:
        pillar_status["International"]["state"] = "AUTH REQUIRED"
        pillar_status["International"]["positions_unknown"] = True
        pillar_status["International"]["freshness"] = "UNKNOWN"
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
    authoritative_accounting = load_authoritative_accounting()
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
    pillar_performance = dict(
        snapshot.get("pillar_performance") if isinstance(snapshot.get("pillar_performance"), dict) else {}
    )
    cash = dict(snapshot.get("cash_dashboard") if isinstance(snapshot.get("cash_dashboard"), dict) else {})
    activity = list(snapshot.get("activity") if isinstance(snapshot.get("activity"), list) else [])
    for job_name in ("autonomous-paper-trading", "saxo-international-paper-trading"):
        audit_cycle = _latest_audit_cycle(job_name)
        if audit_cycle:
            activity.insert(0, audit_cycle)
    legacy_cash = (
        snapshot.get("legacy_cash_dashboard") if isinstance(snapshot.get("legacy_cash_dashboard"), dict) else {}
    )
    broker_account = snapshot.get("broker_account") if isinstance(snapshot.get("broker_account"), dict) else {}
    trades = list(snapshot.get("trades") if isinstance(snapshot.get("trades"), list) else [])
    orders = snapshot.get("orders") if isinstance(snapshot.get("orders"), list) else []
    crypto_history = _alpaca_crypto_history()
    provider_trades = crypto_history.get("trades") if isinstance(crypto_history.get("trades"), list) else []
    provider_transactions = crypto_history.get("transactions") if isinstance(crypto_history.get("transactions"), list) else []
    known_trade_ids = {
        str(row.get("exit_order_id") or row.get("order_id"))
        for row in trades if isinstance(row, dict) and (row.get("exit_order_id") or row.get("order_id"))
    }
    for trade in provider_trades:
        if isinstance(trade, dict) and str(trade.get("exit_order_id") or "") not in known_trade_ids:
            trades.append(trade)
    crypto_realized = sum(_float(row.get("realized_pnl")) for row in provider_trades if isinstance(row, dict))
    crypto_realized_today = _float(crypto_history.get("realized_today"))
    crypto_stats = dict(pillar_performance.get("Crypto") or {})
    if provider_trades:
        pnl_values = [_float(row.get("realized_pnl")) for row in provider_trades]
        wins = [value for value in pnl_values if value > 0]
        losses = [value for value in pnl_values if value < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        crypto_stats.update({
            "number_of_trades": len(provider_trades),
            "completed_trades": len(provider_trades),
            "net_generated_cash": crypto_realized,
            "realized_pnl": crypto_realized,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(provider_trades),
            "average_win": gross_profit / len(wins) if wins else 0.0,
            "average_loss": -gross_loss / len(losses) if losses else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss else 0.0,
            "expectancy": crypto_realized / len(provider_trades),
        })
        pillar_performance["Crypto"] = crypto_stats
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
    # Fund accounting is equity-based: six $1,000 paper allocations plus
    # realized provider P&L plus managed unrealized P&L.  Leveraged Forex
    # notional and legacy Alpaca exposure remain display-only exposures.
    original_capital = FUND_STARTING_CAPITAL
    deployed = sum(
        _float(row.get("strategy_deployed"))
        for row in live_pillar_status.values()
        if isinstance(row, dict) and not row.get("positions_unknown")
    )
    unrealized = _float(live_metrics.get("unrealized_pnl"), _float(cash.get("unrealized_pnl")))
    realized_by_pillar = cash.get("realized_pnl_by_pillar") if isinstance(cash.get("realized_pnl_by_pillar"), dict) else {}
    snapshot_crypto_realized = _float(realized_by_pillar.get("Crypto"))
    net_cash = _float(cash.get("net_trading_cash_generated")) - snapshot_crypto_realized + crypto_realized
    protected_cash = _float(cash.get("protected_cash_reserve"))
    available_cash = max(original_capital + net_cash - deployed - protected_cash, 0.0)
    cash.update({
        "original_capital": original_capital,
        "net_trading_cash_generated": net_cash,
        "realized_pnl": net_cash,
        "daily_realized_pnl": _float(cash.get("daily_realized_pnl")) + crypto_realized_today,
        "total_portfolio_equity": original_capital + net_cash + unrealized,
        "strategy_equity": original_capital + net_cash + unrealized,
        "unrealized_pnl": unrealized,
        "capital_deployed": deployed,
        "available_cash": available_cash,
    })
    total_equity = original_capital + net_cash + unrealized
    daily_realized = _float(cash.get("daily_realized_pnl") or cash.get("daily_realized_return") or cash.get("realized_return"))
    daily_unrealized = _float(cash.get("daily_unrealized_return"))
    cumulative_realized = _float(cash.get("cumulative_realized_return") or cash.get("realized_return"))
    generated_cash_ratio = _float(cash.get("generated_cash_ratio") or cash.get("realized_return"))
    daily_performance = _daily_performance_metrics(cash)
    # Financial totals are owned by the normalized provider ledger.  Legacy
    # snapshot cash/P&L remains available for research and operational context,
    # never as a fallback for these displayed totals.
    accounting_rows = list(authoritative_accounting.values())
    if accounting_rows and all(row.get("economic_equity") is not None for row in accounting_rows):
        total_equity = sum(float(row["economic_equity"]) for row in accounting_rows)
        deployed = sum(float(row.get("deployed_cash") or 0.0) for row in accounting_rows)
        available_cash = sum(float(row["available_cash"]) for row in accounting_rows if row.get("available_cash") is not None)
        protected_cash = sum(float(row.get("pending") or 0.0) for row in accounting_rows)
        unrealized = sum(float(row.get("unrealized") or 0.0) for row in accounting_rows)
        net_cash = sum(float(row.get("realized_today") or 0.0) for row in accounting_rows)
        daily_performance = dict(daily_performance)
        daily_performance.update({
            "current_equity": total_equity,
            "starting_equity": sum(float(row.get("starting_equity") or 0.0) for row in accounting_rows),
            "realized_pnl": net_cash,
            "unrealized_pnl": unrealized,
            "total_pnl": net_cash + unrealized,
        })
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
        "authoritative_accounting": authoritative_accounting,
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
        "provider_transactions": provider_transactions,
        "provider_fills_today": int(crypto_history.get("fills_today") or 0),
        "provider_orders_today": int(crypto_history.get("orders_today") or 0),
        "crypto_realized": crypto_realized,
        "crypto_realized_today": crypto_realized_today,
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
        "daily_performance": daily_performance,
        "dist_low": dist_low,
        "dist_high": dist_high,
    }


def _live_result_totals(ctx: dict[str, object]) -> list[tuple[str, str]]:
    rows = _live_results_rows(ctx)
    def numeric(key: str) -> float:
        return sum(float(row[key]) for row in rows if isinstance(row.get(key), (int, float)))
    return [
        ("CURRENT FUND EQUITY", _money(ctx.get("total_equity"))),
        ("TOTAL REALIZED P&L", _money(ctx.get("net_cash"))),
        ("TOTAL UNREALIZED P&L", _money(ctx.get("unrealized"))),
        ("COMPLETED TRADES", str(int(numeric("completed_trades")))),
        ("WINS", str(int(numeric("wins")))),
        ("LOSSES", str(int(numeric("losses")))),
        ("ACTIVE POSITIONS", str(int(numeric("positions")))),
        ("PILLARS DEPLOYED", str(sum(1 for row in rows if row.get("deployed") is not None and row["deployed"] > 0))),
        ("PILLARS OPERATIONAL", str(sum(1 for row in rows if row.get("status") == "OPERATIONAL"))),
    ]


def _live_results_rows(ctx: dict[str, object]) -> list[dict[str, object]]:
    live_status = ctx.get("live_pillar_status") if isinstance(ctx.get("live_pillar_status"), dict) else {}
    performance = ctx.get("pillar_performance") if isinstance(ctx.get("pillar_performance"), dict) else {}
    metrics = _pillars_from_snapshot(ctx.get("snapshot") if isinstance(ctx.get("snapshot"), dict) else {})
    jobs = ctx.get("jobs") if isinstance(ctx.get("jobs"), dict) else {}
    autopsy = _safe_json(Path("var/autotrader/learning/crypto-active-v2-autopsy.json"))
    registry = autopsy.get("registry") if isinstance(autopsy.get("registry"), dict) else {}
    crypto = registry.get("summary") if isinstance(registry.get("summary"), dict) else {}
    rows = []
    for name, broker, _accent in PILLARS:
        provider = live_status.get(name) if isinstance(live_status.get(name), dict) else {}
        stats = performance.get(name) if isinstance(performance.get(name), dict) else {}
        snap = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
        is_crypto = name == "Crypto" and crypto
        if is_crypto:
            completed = crypto.get("trades")
            wins, losses = crypto.get("wins"), crypto.get("losses")
            realized, expectancy = crypto.get("realized_pnl"), crypto.get("expectancy")
            profit_factor = crypto.get("profit_factor")
        else:
            completed = stats.get("completed_trades", stats.get("number_of_trades"))
            wins, losses = stats.get("wins"), stats.get("losses")
            realized, expectancy = stats.get("realized_pnl", stats.get("net_generated_cash")), stats.get("expectancy")
            profit_factor = stats.get("profit_factor")
        provider_known = bool(provider) and provider.get("connected") is not False
        available = provider.get("available_cash", provider.get("available_balance"))
        deployed = provider.get("strategy_deployed", snap.get("deployed"))
        positions = provider.get("positions", snap.get("positions"))
        pending = provider.get("working_orders", provider.get("pending_orders"))
        if available is None and provider_known and name != "Kalshi":
            authorized = PILLAR_BASE_CAPITAL
            available = max(authorized - _float(deployed) - _float(pending), 0.0) if deployed is not None else None
        if name == "Kalshi":
            kalshi = _kalshi_status()
            connected = kalshi.get("predictions_provider_state") == "CONNECTED" and kalshi.get("perps_provider_state") == "CONNECTED"
            status = "OPERATIONAL" if connected else "DEGRADED"
            deployed = kalshi.get("perps_deployed") if connected else None
            available = max(PILLAR_BASE_CAPITAL - _float(deployed), 0.0) if connected else None
            positions = kalshi.get("perps_positions") if connected else None
            pending = kalshi.get("perps_open_orders") if connected else None
        if name == "Kalshi" and str(_kalshi_status().get("perps_provider_state")) == "DEGRADED":
            deployed = available = positions = pending = None
        status = "OPERATIONAL" if (jobs.get(PILLAR_JOB_MAP[name], {}).get("last_error") is None and provider_known) else "UNKNOWN"
        rows.append({
            "pillar": name, "broker": broker, "completed_trades": completed, "wins": wins, "losses": losses,
            "win_rate": (crypto.get("win_rate") if is_crypto else stats.get("win_rate")), "realized": realized,
            "unrealized": provider.get("unrealized_pnl", snap.get("unrealized_pnl")), "expectancy": expectancy,
            "profit_factor": profit_factor, "deployed": _float(deployed) if deployed is not None else None,
            "available": _float(available) if available is not None else None, "positions": int(_float(positions)) if positions is not None else None,
            "pending": int(_float(pending)) if pending is not None else None,
            "last_fill": (ctx.get("provider_transactions") or [{}])[-1].get("timestamp") if name == "Crypto" and ctx.get("provider_transactions") else jobs.get(PILLAR_JOB_MAP[name], {}).get("last_finished_at"),
            "status": status,
        })
    return rows


def _display(value: object, formatter=None) -> str:
    if value is None:
        return "UNKNOWN"
    return formatter(value) if formatter else str(value)


def _render_live_results(ctx: dict[str, object]) -> None:
    st.markdown("<div class='section-title'>LIVE RESULTS</div>", unsafe_allow_html=True)
    headers = ["PILLAR", "COMPLETED TRADES", "WINS", "LOSSES", "WIN RATE", "REALIZED P&L", "UNREALIZED P&L", "EXPECTANCY", "PROFIT FACTOR", "DEPLOYED / COMMITTED CAPITAL", "AVAILABLE CAPITAL", "OPEN POSITIONS", "PENDING ORDERS", "LAST FILL", "STATUS"]
    body = []
    for row in _live_results_rows(ctx):
        cells = [row["pillar"], _display(row["completed_trades"]), _display(row["wins"]), _display(row["losses"]), _display(row["win_rate"], lambda x: f"{_float(x) * 100:.1f}%"), _display(row["realized"], _money), _display(row["unrealized"], _money), _display(row["expectancy"], _money), _display(row["profit_factor"], lambda x: f"{_float(x):.2f}"), _display(row["deployed"], _money), _display(row["available"], _money), _display(row["positions"]), _display(row["pending"]), _display(row["last_fill"]), row["status"]]
        negative = " class='negative-result'" if isinstance(row.get("realized"), (int, float)) and row["realized"] < 0 else ""
        body.append("<tr" + negative + ">" + "".join(f"<td>{escape(str(cell))}</td>" for cell in cells) + "</tr>")
    st.markdown(f"<div class='table-panel live-results-table'><table><thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead><tbody>{''.join(body)}</tbody></table></div>", unsafe_allow_html=True)


def _render_crypto_strategy_health() -> None:
    autopsy = _safe_json(Path("var/autotrader/learning/crypto-active-v2-autopsy.json"))
    registry = autopsy.get("registry") if isinstance(autopsy.get("registry"), dict) else {}
    summary = registry.get("summary") if isinstance(registry.get("summary"), dict) else {}
    v2_analysis = _safe_json(Path("var/autotrader/learning/crypto-challenger-v2-analysis.json"))
    cf_summary = {}
    try:
        from autotrader.paper_experiment import PaperExperimentLedger
        cf_summary = PaperExperimentLedger().counterfactual_summary()
    except (OSError, sqlite3.Error):
        cf_summary = {}
    st.markdown("<div class='section-title'>CRYPTO ACTIVE-V2 STRATEGY HEALTH</div>", unsafe_allow_html=True)
    values = [("Sample Size", summary.get("trades")), ("Win Rate", _pct(summary.get("win_rate"))), ("Realized P&L", _money(summary.get("realized_pnl"))), ("Expectancy", _money(summary.get("expectancy"))), ("Profit Factor", f"{_float(summary.get('profit_factor')):.2f}"), ("Maximum Drawdown", _money(summary.get("maximum_drawdown"))), ("Average Win", _money(summary.get("average_win"))), ("Average Loss", _money(summary.get("average_loss")))]
    st.markdown("<div class='status-grid'>" + "".join(f"<div class='status-card'><div class='status-label'>{label}</div><div class='status-value {'status-faulted' if isinstance(value, (int, float)) and value < 0 else ''}'>{escape(str(value if value is not None else 'UNKNOWN'))}</div></div>" for label, value in values) + "</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='panel' style='padding:1rem'><div class='small-note'>Champion: <strong>{escape(str(registry.get('champion_version') or 'UNKNOWN'))}</strong> · Challenger: <strong>{escape(str(registry.get('challenger_version') or 'UNKNOWN'))}</strong> · Learning State: <strong>{escape(str(registry.get('state') or 'UNKNOWN'))}</strong> · Promotion Status: <strong>{escape(str(registry.get('promotion_status') or 'UNKNOWN'))}</strong></div></div>", unsafe_allow_html=True)
    champion_cf = cf_summary.get("champion", {}) if isinstance(cf_summary, dict) else {}
    challenger_cf = cf_summary.get("challenger", {}) if isinstance(cf_summary, dict) else {}
    st.markdown(
        f"<div class='panel' style='padding:1rem'><strong>COUNTERFACTUAL LEARNING EVIDENCE</strong><div class='status-grid'>"
        f"<div class='status-card'><div class='status-label'>CHAMPION ACTUAL TRADES</div><div class='status-value'>{escape(str(summary.get('trades', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>CHALLENGER ACTUAL TRADES</div><div class='status-value'>0</div></div>"
        f"<div class='status-card'><div class='status-label'>COUNTERFACTUAL OBSERVATIONS</div><div class='status-value'>{escape(str(cf_summary.get('observations', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>COUNTERFACTUAL EVALUATED</div><div class='status-value'>{escape(str(cf_summary.get('evaluated', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>COUNTERFACTUAL PENDING</div><div class='status-value'>{escape(str(cf_summary.get('pending', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>CHAMPION COUNTERFACTUAL EXPECTANCY</div><div class='status-value'>{escape(_money(champion_cf.get('expectancy')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>CHALLENGER COUNTERFACTUAL EXPECTANCY</div><div class='status-value'>{escape(_money(challenger_cf.get('expectancy')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>CHAMPION COUNTERFACTUAL WIN RATE</div><div class='status-value'>{escape(_pct(champion_cf.get('win_rate')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>CHALLENGER COUNTERFACTUAL WIN RATE</div><div class='status-value'>{escape(_pct(challenger_cf.get('win_rate')))}</div></div>"
        f"</div><div class='small-note'>COUNTERFACTUAL RESULTS ARE SIMULATED RESEARCH OUTCOMES AND ARE NOT PROVIDER FILLS OR FUND P&amp;L.</div></div>",
        unsafe_allow_html=True,
    )
    v2_metrics = v2_analysis.get("v2") if isinstance(v2_analysis.get("v2"), dict) else {}
    oos_metrics = v2_analysis.get("oos_metrics") if isinstance(v2_analysis.get("oos_metrics"), dict) else {}
    v1_metrics = v2_analysis.get("v1") if isinstance(v2_analysis.get("v1"), dict) else {}
    st.markdown(
        f"<div class='panel' style='padding:1rem'><strong>CHALLENGER V2 RESEARCH</strong><div class='status-grid'>"
        f"<div class='status-card'><div class='status-label'>V2 ACTUAL TRADES</div><div class='status-value'>0</div></div>"
        f"<div class='status-card'><div class='status-label'>V2 COUNTERFACTUAL OBSERVATIONS</div><div class='status-value'>{escape(str(v2_metrics.get('sample', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>V2 WIN RATE</div><div class='status-value'>{escape(_pct(v2_metrics.get('win_rate')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>V2 EXPECTANCY</div><div class='status-value'>{escape(_money(v2_metrics.get('expectancy')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>V2 OOS EXPECTANCY</div><div class='status-value'>{escape(_money(oos_metrics.get('expectancy')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>V2 EVIDENCE CONFIDENCE</div><div class='status-value'>{escape(str(v2_analysis.get('evidence_confidence') or 'LOW'))}</div></div>"
        f"<div class='status-card'><div class='status-label'>PROMOTION STATE</div><div class='status-value'>{escape(str(v2_analysis.get('promotion_state') or 'RESEARCH_ONLY'))}</div></div>"
        f"</div><div class='small-note'>WHY V2 IS DIFFERENT: training-only net-edge, spread, and volatility filters over V1 candidates. V1 expectancy: {escape(_money(v1_metrics.get('expectancy')))} · Research/simulated outcomes only — not provider fills or fund P&amp;L.</div></div>",
        unsafe_allow_html=True,
    )
    discovery = _safe_json(Path("var/autotrader/learning/crypto-strategy-discovery.json"))
    tournament = discovery.get("ranked_tournament") if isinstance(discovery.get("ranked_tournament"), list) else []
    top = tournament[0] if tournament else {}
    top_oos = top.get("oos") if isinstance(top.get("oos"), dict) else {}
    st.markdown(
        f"<div class='panel' style='padding:1rem'><strong>CRYPTO STRATEGY DISCOVERY</strong><div class='status-grid'>"
        f"<div class='status-card'><div class='status-label'>TOTAL STRATEGIES TESTED</div><div class='status-value'>{escape(str(discovery.get('strategy_count', 0)))}</div></div>"
        f"<div class='status-card'><div class='status-label'>SURVIVING VALIDATION</div><div class='status-value'>0</div></div>"
        f"<div class='status-card'><div class='status-label'>POSITIVE OOS</div><div class='status-value'>0</div></div>"
        f"<div class='status-card'><div class='status-label'>READY CONTROLLED PAPER</div><div class='status-value'>0</div></div>"
        f"<div class='status-card'><div class='status-label'>CURRENT #1 RESEARCH STRATEGY</div><div class='status-value'>{escape(str(top.get('strategy_id') or 'NONE'))}</div></div>"
        f"<div class='status-card'><div class='status-label'>OOS EXPECTANCY</div><div class='status-value'>{escape(_money(top_oos.get('expectancy')))}</div></div>"
        f"<div class='status-card'><div class='status-label'>PROMOTION STATE</div><div class='status-value'>{escape(str(discovery.get('promotion_state') or 'NO_EDGE_FOUND'))}</div></div>"
        f"</div><div class='small-note'>RESEARCH / COUNTERFACTUAL RESULTS — NOT PROVIDER FILLS OR FUND P&amp;L. {escape(str(discovery.get('no_edge_reason') or 'No discovery result available.'))}</div></div>",
        unsafe_allow_html=True,
    )


def _render_overview_legacy(ctx: dict[str, object]) -> None:
    runtime = ctx["runtime"]
    live_job_rows = ctx["live_job_rows"]
    unresolved = ctx["unresolved"]
    learning = ctx["learning"]
    positions = ctx["positions"]
    broker_account = ctx["broker_account"] if isinstance(ctx["broker_account"], dict) else {}
    legacy_positions = ctx["legacy_positions"] if isinstance(ctx["legacy_positions"], list) else []
    experiment = ctx["experiment"] if isinstance(ctx["experiment"], dict) else {}
    daily = ctx["daily_performance"]
    st.markdown("<div class='section-title'>Overview</div>", unsafe_allow_html=True)
    _render_live_results(ctx)
    _render_crypto_strategy_health()
    st.markdown("<div class='section-title'>CURRENT FUND EQUITY / RESULT STRIP</div>", unsafe_allow_html=True)
    result_strip = _live_result_totals(ctx)
    strip_cols = st.columns(9)
    for col, (label, value) in zip(strip_cols, result_strip, strict=False):
        col.metric(label, value)
    st.markdown("<div class='section-title'>Daily Performance Objectives</div>", unsafe_allow_html=True)
    d1, d2 = st.columns(2)
    d1.metric("TOTAL DAILY RETURN", _pct(daily["daily_return"]))
    d1.caption(f"Floor 20% · {daily['return_floor_progress']:.1%} achieved · Stretch 40% · {daily['return_stretch_progress']:.1%} achieved")
    d2.metric("REALIZED CASH GENERATED", _money(daily["harvested_profit"]))
    d2.caption(f"Floor $500 · {daily['harvest_floor_progress']:.1%} achieved · Stretch $1,000 · {daily['harvest_stretch_progress']:.1%} achieved")
    st.markdown(
        f"<div class='small-note'>Starting equity: <strong>{_money(daily['starting_equity'])}</strong> · "
        f"Current equity: <strong>{_money(daily['current_equity'])}</strong> · "
        f"Total P&amp;L: <strong>{_money(daily['total_pnl'])}</strong> · "
        f"Realized: <strong>{_money(daily['realized_pnl'])}</strong> · "
        f"Unrealized: <strong>{_money(daily['unrealized_pnl'])}</strong> · "
        f"Profit available for redeployment: <strong>{_money(daily['harvested_profit'])}</strong></div>",
        unsafe_allow_html=True,
    )
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
        f"<div class='small-note'>HISTORICAL FIVE-PILLAR BASE: <strong>{_money(TOTAL_BASE_CAPITAL)}</strong> · "
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


def _render_performance_board(ctx: dict[str, object]) -> None:
    daily = ctx.get("daily_performance") if isinstance(ctx.get("daily_performance"), dict) else {}
    rows = _live_results_rows(ctx)
    st.markdown("<div class='section-title'>READ-ONLY PERFORMANCE BOARD</div>", unsafe_allow_html=True)
    st.caption("Observation only · Paper / Practice / Sim / Demo")
    top = st.columns(4)
    for col, label, value in zip(top, ("CURRENT FUND EQUITY", "TODAY'S P&L", "DAILY RETURN %", "CAPITAL DEPLOYED"), (_money(ctx.get("total_equity")), _money(daily.get("total_pnl")), _pct(daily.get("daily_return")), _money(ctx.get("deployed"))), strict=True):
        col.metric(label, value)
    second = st.columns(4)
    for col, label, value in zip(second, ("AVAILABLE CASH", "REALIZED P&L TODAY", "UNREALIZED P&L", "TOTAL RETURN %"), (_money(ctx.get("available_cash")), _money(daily.get("realized_pnl")), _money(ctx.get("unrealized")), _pct(ctx.get("total_equity") / ctx.get("original_capital") - 1 if ctx.get("original_capital") else None)), strict=True):
        col.metric(label, value)
    st.markdown("### CAPITAL ACCOUNTING")
    st.dataframe([{"Starting Capital": _money(ctx.get("original_capital")), "Current Equity": _money(ctx.get("total_equity")), "Deployed": _money(ctx.get("deployed")), "Available Cash": _money(ctx.get("available_cash")), "Pending Capital": _money(ctx.get("protected_cash")), "Utilization": _pct(_float(ctx.get("deployed")) / _float(ctx.get("original_capital")) if _float(ctx.get("original_capital")) else None), "Cumulative P&L": _money(ctx.get("net_cash"))}], hide_index=True, use_container_width=True)
    st.markdown("### TODAY")
    today = st.columns(6)
    for col, label, value in zip(today, ("Daily Starting Equity", "Current Equity", "Realized P&L", "Unrealized P&L", "Net Daily P&L", "Daily Return"), (_money(daily.get("starting_equity")), _money(daily.get("current_equity")), _money(daily.get("realized_pnl")), _money(daily.get("unrealized_pnl")), _money(daily.get("total_pnl")), _pct(daily.get("daily_return"))), strict=True):
        col.metric(label, value)
    st.markdown("### CASH GENERATED")
    cash = st.columns(5)
    for col, label, value in zip(cash, ("Realized Profit Today", "Realized This Week", "Realized This Month", "Realized YTD", "Daily Cash Objective"), (_money(daily.get("harvested_profit")), "INSUFFICIENT DATA", "INSUFFICIENT DATA", _money(ctx.get("net_cash")), "$500 FLOOR / $1,000 STRETCH"), strict=True):
        col.metric(label, value)
    st.markdown("### SIX PILLAR PERFORMANCE")
    pillar_cols = st.columns(3)
    for index, row in enumerate(rows):
        with pillar_cols[index % 3]:
            st.markdown(f"**{row['pillar']}** · {row['status']}")
            st.dataframe([{"Equity": _money((row.get("deployed") or 0) + (row.get("available") or 0)) if row.get("deployed") is not None and row.get("available") is not None else "N/A", "Authorized": _money((row.get("deployed") or 0) + (row.get("available") or 0)) if row.get("deployed") is not None and row.get("available") is not None else "N/A", "Deployed": _money(row.get("deployed")), "Available": _money(row.get("available")), "Today": "N/A", "Unrealized": _money(row.get("unrealized")), "Positions": row.get("positions") if row.get("positions") is not None else "N/A", "Orders": row.get("pending") if row.get("pending") is not None else "N/A"}], hide_index=True, use_container_width=True)
    st.markdown("### PILLAR PERFORMANCE RANKING")
    ranking = sorted(rows, key=lambda row: _float(row.get("realized")), reverse=True)
    st.dataframe([{"Rank": i + 1, "Pillar": row["pillar"], "Today's P&L": _money(row.get("realized")), "Total P&L": _money((_float(row.get("realized")) + _float(row.get("unrealized"))))} for i, row in enumerate(ranking)], hide_index=True, use_container_width=True)
    st.markdown("### CURRENT POSITIONS")
    positions = ctx.get("positions") if isinstance(ctx.get("positions"), list) else []
    st.dataframe([{"Pillar": p.get("pillar", "N/A"), "Asset": p.get("symbol", p.get("asset", "N/A")), "Side": p.get("side", "N/A"), "Current Value": p.get("market_value", p.get("value", "N/A")), "Unrealized P&L": p.get("unrealized_pnl", "N/A")} for p in positions], hide_index=True, use_container_width=True)
    st.markdown("### RECENT CLOSED TRADES")
    trades = ctx.get("trades") if isinstance(ctx.get("trades"), list) else []
    st.dataframe([{"Time": t.get("timestamp", t.get("occurred_at", "N/A")), "Pillar": t.get("pillar", "N/A"), "Asset": t.get("symbol", "N/A"), "Realized P&L": t.get("realized_pnl", t.get("pnl", "N/A"))} for t in trades[:10]], hide_index=True, use_container_width=True)
    st.markdown("### $250,000 ANNUAL REALIZED-INCOME OBJECTIVE")
    st.dataframe([{"Goal": "$250,000", "YTD Realized": _money(ctx.get("net_cash")), "Projected": "INSUFFICIENT DATA", "Remaining": _money(max(250000 - _float(ctx.get("net_cash")), 0))}], hide_index=True, use_container_width=True)
    discovery = _safe_json(Path("var/autotrader/learning/crypto-strategy-discovery.json"))
    health = _safe_json(Path("var/autotrader/learning/crypto-data-health.json"))
    historical = sum(int(item.get("bar_count") or 0) for tf in health.get("timeframes", {}).values() if isinstance(tf, dict) for item in tf.values() if isinstance(item, dict))
    st.caption(f"LEARNING: ACTIVE · RESEARCH SOURCES: {len(_safe_json(Path('var/autotrader/learning/research-source-registry.json')).get('active_sources', []))} · CHALLENGERS: {len(discovery.get('strategy_families', []))} · HISTORICAL DATA: {historical} BARS · LAST UPDATE: {discovery.get('generated_at', 'N/A')}")


def _render_overview(ctx: dict[str, object]) -> None:
    _render_performance_board(ctx)


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
    daily_realized = _float(cash.get("daily_realized_pnl") or cash.get("daily_realized_return") or cash.get("realized_return"))
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
        @media (max-width:768px){.alloc-grid,.status-grid,.fund-target-grid{grid-template-columns:1fr;}.block-container{padding-left:.9rem;padding-right:.9rem;}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        """
        <div class="brand-box">
          <div class="brand-mark">CH</div>
          <div class="brand-name">Chris Haake<br>Capital Systems</div>
          <div class="brand-sub">SIX-PILLAR AUTONOMOUS SYSTEM</div>
          <div class="brand-sub">Christopher J. Haake</div>
          <div class="brand-footer">Research. Discipline. Execution.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="hero-title">SIX-PILLAR AUTONOMOUS TRADING COMMAND CENTER</div>
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
          <div class="status-card"><div class="status-label">SIX-PILLAR STATUS</div><div class="status-value">{escape(five_state)}</div></div>
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

    st.markdown("<div class='section-title'>Six Pillars</div>", unsafe_allow_html=True)
    pillar_view = []
    kalshi_status = _kalshi_status()
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
                    live_state.get("strategy_market_value", live_state.get("gross_exposure", 0.0))
                    if name != "Forex"
                    else live_metrics.get("oanda_exposure", 0.0)
                ),
                "available": max(
                    PILLAR_BASE_CAPITAL
                    - _float(
                        live_state.get("strategy_market_value", live_state.get("gross_exposure", 0.0))
                        if name != "Forex"
                        else live_metrics.get("oanda_exposure", 0.0)
                    ),
                    0.0,
                ),
                "realized_pnl": _float((pillar_performance.get(name) or {}).get("net_generated_cash")),
                "unrealized_pnl": _float(live_state.get("unrealized_pnl", 0.0)),
                "positions": positions_count,
                "positions_unknown": bool(live_state.get("positions_unknown")),
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
                "data": "FRESH" if job.get("last_finished_at") else "UNAVAILABLE",
                "research": "DEGRADED" if job.get("last_error") else ("STOPPED" if job.get("disabled") else "ACTIVE"),
                "learning": "ACTIVE" if not job.get("last_error") and not job.get("disabled") else ("DEGRADED" if job.get("last_error") else "STOPPED"),
                "evidence": "COLLECTING",
                "last_research": job.get("last_finished_at") or job.get("last_started_at"),
                "last_learning": (jobs.get("daily-learning", {}) or {}).get("last_finished_at") if isinstance(jobs.get("daily-learning"), dict) else None,
            }
        )
        if name == "Kalshi":
            kalshi_state, kalshi_blocker = _kalshi_parent_state(kalshi_status)
            pillar_view[-1].update(
                {
                    "connection": kalshi_status["connection"],
                    "connection_class": "good" if str(kalshi_status["connection"]).startswith("CONNECTED") else "warn",
                    "data": kalshi_status["data"],
                    "scanner": kalshi_status["scanner"],
                    "research": kalshi_status["research"],
                    "learning": kalshi_status["learning"],
                    "evidence": kalshi_status["evidence"],
                    "observations": kalshi_status["observations"],
                    "features": kalshi_status["features"],
                    "cross_market": kalshi_status["cross_market"],
                    "perps_rest": kalshi_status["perps_rest"],
                    "perps_margin": kalshi_status["perps_margin"],
                    "last_rejection": f"Predictions {kalshi_status['predictions_rejection']} · Perps {kalshi_status['perps_rejection']}",
                    "last_scan": kalshi_status["last_data"],
                    "last_decision": "HOLD_CASH · no qualifying opportunity",
                    "last_research": kalshi_status["last_data"],
                    "last_learning": kalshi_status["last_learning"],
                    "execution": "NO QUALIFYING OPPORTUNITY",
                    "blocker": f"{kalshi_blocker} · Perps {kalshi_status['perps_account']} · {kalshi_status['perps_markets']} markets",
                    "state": kalshi_state,
                }
            )

    for row in (pillar_view[:2], pillar_view[2:4], pillar_view[4:]):
        cols = st.columns(len(row))
        for col, pillar in zip(cols, row, strict=False):
            with col:
                _render_pillar_card(pillar["name"], pillar)

    metals_cycles = [
        row for row in activity
        if isinstance(row, dict)
        and str(row.get("job") or "") == "alpaca-metals-paper-trading"
        and isinstance(row.get("metals_diagnostics"), list)
    ]
    if metals_cycles:
        latest_metals = metals_cycles[0]
        diagnostics = latest_metals.get("metals_diagnostics", [])
        st.markdown("<div class='section-title'>Metals Strategy Readiness</div>", unsafe_allow_html=True)
        st.dataframe(
            [
                {
                    "Symbol": row.get("symbol"),
                    "History Bars": row.get("bars_available"),
                    "Required Bars": row.get("bars_required"),
                    "Data Valid": row.get("data_valid"),
                    "Scanner Score": row.get("scanner_score"),
                    "Strategy Evaluated": row.get("strategy_evaluated"),
                    "Strategy Vote": row.get("strategy_vote"),
                    "Risk Approved": row.get("risk_approved"),
                    "Capital Approved": row.get("capital_approved"),
                    "Qualified": row.get("qualified"),
                    "Orders": 0,
                    "Fills": 0,
                    "Positions": 0,
                    "Rejection": row.get("rejection"),
                }
                for row in diagnostics
            ],
            use_container_width=True,
            hide_index=True,
        )

    crypto_cycles = [
        row for row in activity
        if isinstance(row, dict)
        and str(row.get("job") or "") == "autonomous-paper-trading"
        and row.get("paper_experiment_enabled") is not None
        and isinstance(row.get("eligible_crypto_universe"), list)
    ]
    if crypto_cycles:
        latest_crypto = crypto_cycles[0]
        st.markdown("<div class='section-title'>Paper Learning Experiment</div>", unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Mode", "ENABLED" if latest_crypto.get("paper_experiment_enabled") else "BASELINE ONLY")
        c2.metric("Provider Crypto", str(len(latest_crypto.get("provider_crypto_universe") or [])))
        c3.metric("Eligible Crypto", str(len(latest_crypto.get("eligible_crypto_universe") or [])))
        c4.metric("Baseline Candidates", str(latest_crypto.get("baseline_candidates") or 0))
        c5.metric("Experimental Candidates", str(latest_crypto.get("experimental_candidates") or 0))
        crypto_qualified = int(latest_crypto.get("crypto_qualified") or 0)
        crypto_scanned = int(latest_crypto.get("crypto_scanned") or 0)
        st.info(
            f"WHY NO NEW TRADE? {'NO QUALIFIED EDGE' if crypto_qualified == 0 else 'QUALIFIED CANDIDATES REJECTED BY LATER GATES'} · "
            f"{crypto_scanned} Crypto instruments evaluated"
        )
        managed = latest_crypto.get("position_management") if isinstance(latest_crypto.get("position_management"), list) else []
        if managed:
            st.markdown("<div class='status-value'>ACTIVE — POSITION MANAGEMENT</div>", unsafe_allow_html=True)
            st.dataframe(
                [
                    {
                        "Symbol": row.get("symbol"),
                        "Current Signal": row.get("strategy") or "—",
                        "Current Edge": (_float((row.get("current_edge") or {}).get("expected_net_edge")) if isinstance(row.get("current_edge"), dict) else None),
                        "Decision": row.get("decision"),
                        "Reason": row.get("reason"),
                        "Capital": _money(row.get("capital")),
                    }
                    for row in managed
                ], use_container_width=True, hide_index=True,
            )
            st.caption("Positions evaluated this cycle: {} · exit candidates: {} · rotation decisions: {}".format(
                len(managed), sum(1 for row in managed if str(row.get("decision", "")).startswith("EXIT")), len(managed)))
        st.caption("Experimental entries are PAPER-only challengers with explicit cost-positive edge assumptions; baseline evidence remains separate.")
        quality = _safe_json(Path("var/autotrader/learning/crypto-execution-quality.json"))
        if isinstance(quality, dict):
            quality_rows = []
            for symbol, row in quality.items():
                if not isinstance(row, dict):
                    continue
                quality_rows.append({
                    "Symbol": symbol,
                    "Execution Quality": row.get("execution_quality_score", "—"),
                    "Cooldown": row.get("cooldown_until") or "—",
                    "Submitted": row.get("submitted", 0),
                    "Filled": row.get("filled", 0),
                    "Partial": row.get("partial", 0),
                    "Stale": row.get("stale", 0),
                    "Rejected": row.get("rejected", 0),
                    "Last Event": (row.get("events") or [{}])[-1].get("event", "—") if isinstance((row.get("events") or [{}])[-1], dict) else "—",
                })
            if quality_rows:
                st.caption("Crypto execution quality and cooldown")
                st.dataframe(quality_rows, use_container_width=True, hide_index=True)
    crypto_live = [row for row in live_positions if isinstance(row, dict) and str(row.get("pillar") or "") == "Crypto"]
    crypto_deployed = sum(_float(row.get("market_value")) for row in crypto_live)
    largest_crypto = max((_float(row.get("market_value")) for row in crypto_live), default=0.0)
    crypto_cap = _float((crypto_cycles[0] if crypto_cycles else {}).get("experimental_position_cap_pct"), 0.20)
    if crypto_live:
        st.markdown("<div class='small-note'>Crypto capital concentration: <strong>{:.2f}% deployed</strong> · largest position <strong>{:.2f}% of pillar</strong> · future experimental position cap <strong>{:.2f}%</strong> · available capacity <strong>{}</strong></div>".format(crypto_deployed / PILLAR_BASE_CAPITAL * 100.0, largest_crypto / PILLAR_BASE_CAPITAL * 100.0, crypto_cap * 100.0, _money(max(PILLAR_BASE_CAPITAL - crypto_deployed, 0.0))), unsafe_allow_html=True)

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
    .fund-command{padding:1rem 1.1rem;margin:.8rem 0;border:1px solid rgba(255,205,90,.35);border-radius:14px;background:linear-gradient(120deg,rgba(255,205,90,.12),rgba(75,160,255,.08));}
    .fund-target-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.6rem;margin:.6rem 0 1rem;}
    .fund-target-grid>div{padding:.7rem;border:1px solid var(--line);border-radius:10px;color:var(--muted);font-size:.78rem;line-height:1.45;}
    .fund-target-grid strong{color:var(--text);font-size:.68rem;letter-spacing:.1em;}
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
    .pillar{padding:.95rem;min-height:260px;min-width:0;position:relative;overflow:hidden;}
    .pillar::before{content:'';position:absolute;inset:0 auto auto 0;width:100%;height:3px;background:var(--accent,var(--gold));opacity:.88;}
    .pillar-blue{--accent:var(--blue);}.pillar-green{--accent:var(--green);}.pillar-purple{--accent:var(--purple);}.pillar-gold{--accent:var(--orange);}.pillar-teal{--accent:var(--teal);}
    .pillar-top{display:flex;justify-content:space-between;gap:.6rem;align-items:flex-start;margin-bottom:.7rem;}
    .pillar-name{font-size:.92rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;overflow-wrap:normal;word-break:normal;}
    .pillar-sub{color:var(--muted);font-size:.75rem;margin-top:.2rem;}
    .pillar-state{font-size:1.05rem;font-weight:800;margin:.4rem 0 .7rem;color:var(--text);}
    .pillar-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem .7rem;}
    .pillar-grid span,.pillar-foot span{display:block;color:var(--muted);font-size:.67rem;text-transform:uppercase;letter-spacing:.14em;}
    .pillar-grid strong,.pillar-foot strong{display:block;margin-top:.15rem;font-size:.88rem;overflow-wrap:anywhere;word-break:normal;}
    .pillar-foot{display:grid;gap:.45rem;margin-top:.7rem;}
    .table-panel{padding:.85rem;overflow-x:auto;}
    .live-results-table{border-color:rgba(215,181,109,.5);box-shadow:0 18px 48px rgba(0,0,0,.3);}
    .live-results-table th{white-space:nowrap;}
    .live-results-table .negative-result td{color:#ff8585;}
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
    @media (max-width:768px){.block-container{padding-left:.9rem;padding-right:.9rem;}.activation-head{grid-template-columns:repeat(2,minmax(0,1fr));}.fund-target-grid{grid-template-columns:1fr;}[data-testid="stSidebar"] [data-testid="stRadio"] label{font-size:.9rem!important;}}
    </style>
    """


def _render_dashboard_shell(ctx: dict[str, object], selected_view: str) -> None:
    runtime = ctx["runtime"] if isinstance(ctx["runtime"], dict) else {}
    live_runtime = ctx["runtime_source"]
    runtime_labels = ctx["runtime_labels"]
    st.markdown(
        """
        <div class="hero-title">SIX-PILLAR AUTONOMOUS TRADING COMMAND CENTER</div>
        <div class="hero-sub">Research · Execution · Learning · Capital Discipline</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("CHRIS HAAKE CAPITAL SYSTEMS")
    _render_fund_command_center(ctx)
    st.markdown(
        f"""
        <div class="small-note">Runtime source: <strong>{escape(str(live_runtime))}</strong> · freshness: <strong>{escape(str(ctx["runtime_source_age"]))}</strong></div>
        <div class="status-grid">
          <div class="status-card"><div class="status-label">SYSTEM STATUS</div><div class="status-value {"status-healthy" if runtime_labels["runtime_health"] == "Healthy" else "status-faulted"}">{escape(runtime_labels["runtime_health"])}</div></div>
          <div class="status-card"><div class="status-label">AUTONOMOUS PAPER</div><div class="status-value {"status-armed" if ctx["autonomous_state"] == "ARMED" else "status-disarmed"}">{escape(str(ctx["autonomous_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LIVE TRADING</div><div class="status-value status-disabled">{escape(str(ctx["live_state"]))}</div></div>
          <div class="status-card"><div class="status-label">SIX-PILLAR STATUS</div><div class="status-value">{escape(str(ctx["five_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LEARNING ENGINE</div><div class="status-value">{escape(str(ctx["learning_engine_state"]))}</div></div>
          <div class="status-card"><div class="status-label">LAST HEARTBEAT</div><div class="status-value">{escape(str(ctx["heartbeat_age"]))}</div></div>
          <div class="status-card"><div class="status-label">LAST CYCLE</div><div class="status-value">{escape(str(ctx["cycle_age"]))}</div></div>
          <div class="status-card"><div class="status-label">CURRENT UTC TIME</div><div class="status-value">{escape(datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))} UTC</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    discovery = _safe_json(Path("var/autotrader/learning/crypto-strategy-discovery.json"))
    source_registry = _safe_json(Path("var/autotrader/learning/research-source-registry.json"))
    source_count = len(source_registry.get("active_sources", [])) if isinstance(source_registry.get("active_sources"), list) else 0
    challenger_count = len(discovery.get("strategy_families", [])) if isinstance(discovery.get("strategy_families"), list) else 0
    last_update = discovery.get("generated_at", "UNKNOWN")
    st.markdown(
        f"<div class='small-note'>LEARNING: <strong>ACTIVE</strong> · RESEARCH SOURCES: <strong>{source_count}</strong> · CHALLENGERS: <strong>{challenger_count}</strong> · LAST RESEARCH UPDATE: <strong>{escape(str(last_update))}</strong></div>",
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


def _render_fund_command_center(ctx: dict[str, object]) -> None:
    daily = ctx.get("daily_performance") if isinstance(ctx.get("daily_performance"), dict) else {}
    realized_ytd = _float(ctx.get("net_cash"))
    current_equity = _float(ctx.get("total_equity"))
    remaining = max(ANNUAL_REALIZED_INCOME_TARGET - realized_ytd, 0.0)
    st.markdown(
        "<div class='fund-command'><div class='hero-title'>AUTONOMOUS MULTI-PILLAR FUND</div>"
        "<div class='hero-sub'>$6,000 PAPER CAPITAL → $250,000 ANNUAL REALIZED-INCOME OBJECTIVE</div></div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(6)
    cols[0].metric("STARTING CAPITAL", _money(FUND_STARTING_CAPITAL))
    cols[1].metric("CURRENT FUND EQUITY", _money(current_equity))
    cols[2].metric("ANNUAL INCOME OBJECTIVE", _money(ANNUAL_REALIZED_INCOME_TARGET))
    cols[3].metric("REALIZED YTD", _money(realized_ytd))
    cols[4].metric("PROJECTED ANNUAL INCOME", "INSUFFICIENT DATA")
    cols[5].metric("REMAINING TO TARGET", _money(remaining))
    st.markdown(
        f"<div class='fund-target-grid'><div><strong>DAILY RETURN OBJECTIVE</strong><br>20% FLOOR · 40% STRETCH</div>"
        f"<div><strong>REALIZED CASH HARVEST</strong><br>$500 FLOOR · $1,000 STRETCH</div>"
        f"<div><strong>MONTHLY TARGET</strong><br>{_money(MONTHLY_REALIZED_TARGET)}</div>"
        f"<div><strong>WEEKLY TARGET</strong><br>{_money(WEEKLY_REALIZED_TARGET)}</div>"
        f"<div><strong>DAILY REALIZED CASH</strong><br>{_money(daily.get('harvested_profit'))}</div>"
        f"<div><strong>PROJECTION</strong><br>INSUFFICIENT DATA — ACTUAL RESULTS ONLY</div></div>",
        unsafe_allow_html=True,
    )


def _render_proof_of_concept(ctx: dict[str, object]) -> None:
    statuses = ctx.get("live_pillar_status") if isinstance(ctx.get("live_pillar_status"), dict) else {}
    kalshi = _kalshi_status()
    connected_non_kalshi = sum(1 for name in ("US Stocks / ETFs", "Crypto", "Forex", "Metals / Commodities", "International") if (statuses.get(name) or {}).get("connected"))
    predictions_operational = str(kalshi.get("predictions_provider_state")) == "CONNECTED"
    perps_operational = str(kalshi.get("perps_provider_state")) == "CONNECTED"
    connected = connected_non_kalshi + int(predictions_operational and perps_operational)
    execution_engines = connected_non_kalshi + int(predictions_operational) + int(perps_operational)
    deployed_or_pending = sum(
        1 for name, state in statuses.items()
        if _float(state.get("strategy_deployed")) > 0 or _float(state.get("pending_capital")) > 0
    )
    positions = sum(int(_float(state.get("positions"))) for state in statuses.values())
    trades = ctx.get("trades") if isinstance(ctx.get("trades"), list) else []
    provider_transactions = ctx.get("provider_transactions") if isinstance(ctx.get("provider_transactions"), list) else []
    fills_today = int(ctx.get("provider_fills_today") or 0) + int(kalshi.get("perps_fills", 0) or 0)
    orders_today = int(ctx.get("provider_orders_today") or 0)
    st.markdown("<div class='section-title'>Proof of Concept Status</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='small-note'>Top-level pillars operational: <strong>{connected}/6</strong> · "
        f"Execution engines operational: <strong>{execution_engines}/7</strong> · "
        f"Pillars with deployed/pending capital: <strong>{deployed_or_pending}/6</strong> · "
        f"Orders today: <strong>{orders_today}</strong> · Fills today: <strong>{fills_today}</strong> · "
        f"Positions: <strong>{positions}</strong> · Realized P&amp;L today: <strong>{_money(ctx.get('daily_realized'))}</strong> · "
        f"Provider truth synchronized: <strong>{'YES' if kalshi.get('perps_provider_state') != 'DEGRADED' else 'NO — KALSHI MARGIN READ'}</strong> · "
        f"Learning Health: <strong>{'ACTIVE' if kalshi.get('learning') == 'ACTIVE' else 'DEGRADED'}</strong></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='section-title'>Recent Transactions</div>", unsafe_allow_html=True)
    rows = []
    lifecycle_order_ids = {
        str(trade.get(key) or "")
        for trade in trades if isinstance(trade, dict)
        for key in ("entry_order_id", "exit_order_id")
    }
    selected_transactions = [
        transaction for transaction in provider_transactions
        if isinstance(transaction, dict) and str(transaction.get("order_id") or "") in lifecycle_order_ids
    ]
    selected_transactions.extend(provider_transactions[-20:])
    seen_transaction_ids: set[str] = set()
    for transaction in selected_transactions:
        if isinstance(transaction, dict):
            transaction_id = str(transaction.get("order_id") or transaction.get("timestamp") or "")
            if transaction_id in seen_transaction_ids:
                continue
            seen_transaction_ids.add(transaction_id)
            rows.append({
                "Time": transaction.get("timestamp"),
                "Pillar": transaction.get("pillar"), "Engine": transaction.get("engine"),
                "Symbol": transaction.get("symbol"), "Side": transaction.get("side"),
                "Action": transaction.get("action"), "Quantity": transaction.get("quantity"),
                "Price": transaction.get("price"), "Status": transaction.get("status"),
                "Realized P&L": transaction.get("realized_pnl"), "Source": transaction.get("source"),
            })
    for trade in trades[-20:]:
        if isinstance(trade, dict):
            rows.append({
                "Time": trade.get("timestamp") or trade.get("closed_at") or trade.get("opened_at"),
                "Pillar": trade.get("pillar"), "Engine": trade.get("broker"),
                "Symbol": trade.get("symbol"), "Side": trade.get("side"),
                "Action": trade.get("exit_reason") or trade.get("lifecycle_state") or "TRADE",
                "Quantity": trade.get("quantity"), "Price": trade.get("exit_price") or trade.get("fill_price"),
                "Status": trade.get("status") or trade.get("lifecycle_state"),
                "Realized P&L": trade.get("realized_pnl"), "Source": "provider/ledger",
            })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No completed provider transactions are currently available in the local trade view; live child-provider counts remain visible in the pillar cards.")
def _render_pillars_view(ctx: dict[str, object]) -> None:
    pillar_rows: list[dict[str, object]] = []
    live_pillar_status = ctx["live_pillar_status"] if isinstance(ctx["live_pillar_status"], dict) else {}
    pillar_performance = ctx["pillar_performance"] if isinstance(ctx["pillar_performance"], dict) else {}
    jobs = ctx["jobs"] if isinstance(ctx["jobs"], dict) else {}
    runtime = ctx["runtime"] if isinstance(ctx["runtime"], dict) else {}
    activity = ctx["activity"] if isinstance(ctx["activity"], list) else []
    v2_metrics = _pillars_from_snapshot(ctx["snapshot"])
    authoritative = ctx.get("authoritative_accounting") if isinstance(ctx.get("authoritative_accounting"), dict) else {}
    kalshi_status = _kalshi_status()
    _render_live_results(ctx)
    _render_crypto_strategy_health()
    _render_proof_of_concept(ctx)
    for name, broker, accent in PILLARS:
        job_name = PILLAR_JOB_MAP[name]
        job = jobs.get(job_name) if isinstance(jobs, dict) else {}
        job = job if isinstance(job, dict) else {}
        broker_state = live_pillar_status.get(name) if isinstance(live_pillar_status, dict) else {}
        broker_state = broker_state if isinstance(broker_state, dict) else {}
        ledger_name = {"US Stocks / ETFs": "Stocks", "Metals / Commodities": "Metals/Commodities"}.get(name, name)
        ledger_row = authoritative.get(ledger_name) if isinstance(authoritative.get(ledger_name), dict) else None
        if ledger_row is not None:
            broker_state = dict(broker_state)
            broker_state.update({
                "strategy_deployed": ledger_row.get("deployed_cash"),
                "strategy_cost_basis": ledger_row.get("deployed_cash"),
                "strategy_market_value": ledger_row.get("position_market_value"),
                "pending_capital": ledger_row.get("pending"),
                "available_cash": ledger_row.get("available_cash"),
                "unrealized_pnl": ledger_row.get("unrealized"),
                "positions": ledger_row.get("positions"),
                "working_orders": ledger_row.get("working_orders"),
                "freshness": ledger_row.get("freshness"),
                "accounting_status": ledger_row.get("accounting_status"),
            })
        positions_count = int(broker_state.get("positions", (v2_metrics.get(name) or {}).get("positions", 0)) or 0)
        strategy_deployed = _float(broker_state.get("strategy_deployed", (v2_metrics.get(name) or {}).get("deployed", 0.0)))
        current_state, connection, blocker = _derive_pillar_state(name, job, broker_state, activity)
        if name == "International" and isinstance(job, dict):
            discovered = job.get("instruments_discovered")
            evaluated = job.get("instruments_evaluated")
            venues = job.get("venues_open")
            if discovered is not None:
                blocker = (
                    f"{venues or 0} foreign venues open · {evaluated or 0}/{discovered} instruments evaluated"
                )
        if name == "Metals / Commodities" and positions_count > 0 and strategy_deployed > 0:
            current_state = "ACTIVE — POSITION OPEN"
            blocker = "SIL PAPER position active"
        if name == "Crypto" and positions_count > 0 and strategy_deployed > 0:
            current_state = "ACTIVE — POSITION MANAGEMENT"
            active_symbols = sorted({
                str(row.get("symbol")) for row in ctx.get("live_positions", [])
                if isinstance(row, dict) and row.get("pillar") == "Crypto"
                and str(row.get("classification") or "").upper() == "VALID_STRATEGY_POSITION"
            })
            blocker = f"{', '.join(active_symbols) or 'Crypto'} PAPER position active"
        if name == "Kalshi":
            connection = str(kalshi_status["connection"])
            current_state, kalshi_blocker = _kalshi_parent_state(kalshi_status)
            blocker = f"{kalshi_blocker} · Perps {kalshi_status['perps_margin']} · {kalshi_status['perps_markets']} markets"
        connection_class = "good" if connection == "CONNECTED" else ("warn" if connection in {"AUTH REQUIRED", "ERROR"} else "neutral")
        pillar_rows.append(
            {
                "name": name,
                "broker": broker,
                "accent": accent,
                "cap": PILLAR_BASE_CAPITAL,
                "deployed": strategy_deployed,
                "cost_basis": _float(broker_state.get("strategy_cost_basis", strategy_deployed)),
                "market_value": _float(broker_state.get("strategy_market_value", strategy_deployed)),
                "gross_notional": _float(broker_state.get("gross_notional", 0.0)),
                "margin_used": _float(broker_state.get("margin_used", 0.0)),
                "pending": _float(broker_state.get("pending_capital")),
                "available": ledger_row.get("available_cash") if ledger_row is not None else max(PILLAR_BASE_CAPITAL - strategy_deployed - _float(broker_state.get("pending_capital")), 0.0),
                "realized_pnl": ledger_row.get("realized_today") if ledger_row is not None else _float((pillar_performance.get(name) or {}).get("net_generated_cash")),
                "unrealized_pnl": _float(broker_state.get("unrealized_pnl", (v2_metrics.get(name) or {}).get("unrealized_pnl", 0.0))),
                "positions": positions_count,
                "positions_unknown": bool(broker_state.get("positions_unknown")),
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
                "execution": "READY / EVALUATING" if not job.get("disabled") and not job.get("last_error") else "DEGRADED",
                "state": current_state,
                "blocker": blocker,
                "legacy_exposure": _float(broker_state.get("legacy_exposure", 0.0)),
                "legacy_positions": max(int(broker_state.get("broker_positions", 0) or 0) - positions_count, 0),
                "data": broker_state.get("freshness") or (v2_metrics.get(name) or {}).get("data", "FRESH" if (v2_metrics.get(name) or {}).get("connection") == "CONNECTED" else "UNAVAILABLE"),
                "research": (v2_metrics.get(name) or {}).get("research", "ACTIVE" if (v2_metrics.get(name) or {}).get("connection") == "CONNECTED" else "UNAVAILABLE"),
                "learning": (v2_metrics.get(name) or {}).get("learning", "ACTIVE" if (v2_metrics.get(name) or {}).get("connection") == "CONNECTED" else "UNAVAILABLE"),
                "evidence": (v2_metrics.get(name) or {}).get("evidence", "COLLECTING"),
                "last_research": (v2_metrics.get(name) or {}).get("last_research") or job.get("last_finished_at"),
                "last_learning": (v2_metrics.get(name) or {}).get("last_learning") or runtime.get("last_heartbeat_at"),
                "observations": (v2_metrics.get(name) or {}).get("observations", 0),
                "features": (v2_metrics.get(name) or {}).get("features", 0),
                "cross_market": (v2_metrics.get(name) or {}).get("cross_market", 0),
            }
        )
        if name == "Kalshi":
            pillar_rows[-1].update({
                "connection": kalshi_status["connection"],
                "connection_class": "good",
                "data": kalshi_status["data"],
                "research": kalshi_status["research"],
                "learning": kalshi_status["learning"],
                "evidence": kalshi_status["evidence"],
                "observations": kalshi_status["observations"],
                "features": kalshi_status["features"],
                "cross_market": kalshi_status["cross_market"],
                "last_research": kalshi_status["last_data"],
                "last_learning": kalshi_status["last_learning"],
                "perps_rest": kalshi_status["perps_rest"],
                "perps_margin": kalshi_status["perps_margin"],
                "deployed": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_deployed"],
                "cost_basis": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_deployed"],
                "margin_used": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_deployed"],
                "market_value": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_deployed"] + kalshi_status["perps_unrealized_pnl"],
                "unrealized_pnl": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_unrealized_pnl"],
                "positions": None if kalshi_status["perps_provider_state"] == "DEGRADED" else kalshi_status["perps_positions"],
                "positions_unknown": kalshi_status["perps_provider_state"] == "DEGRADED",
                "capital_unknown": kalshi_status["perps_provider_state"] == "DEGRADED",
                "available": None if kalshi_status["perps_provider_state"] == "DEGRADED" else max(KALSHI_BASE_CAPITAL - kalshi_status["perps_deployed"], 0.0),
                "last_rejection": f"Predictions {kalshi_status['predictions_rejection']} · Perps {kalshi_status['perps_rejection']}",
                "execution": current_state,
                "state": current_state,
                "last_scan": kalshi_status["perps_cycle"],
                "last_decision": (
                    f"LAST CONFIRMED PROVIDER FILL COUNT: {kalshi_status['perps_fills']} · "
                    f"READ ERROR: {kalshi_status['perps_provider_error']}"
                    if kalshi_status["perps_provider_state"] == "DEGRADED"
                    else ("POSITION ACTIVE" if kalshi_status["perps_positions"] else "HOLD CASH")
                ),
            })
    st.markdown("<div class='section-title'>Six Pillars</div>", unsafe_allow_html=True)
    for row in (pillar_rows[:2], pillar_rows[2:4], pillar_rows[4:]):
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
    autopsy = _safe_json(Path("var/autotrader/learning/crypto-active-v2-autopsy.json"))
    autopsy_registry = autopsy.get("registry") if isinstance(autopsy.get("registry"), dict) else {}
    autopsy_summary = autopsy_registry.get("summary") if isinstance(autopsy_registry.get("summary"), dict) else {}
    if autopsy_summary:
        st.markdown("<div class='section-title'>Crypto ACTIVE-V2 Learning</div>", unsafe_allow_html=True)
        a1, a2, a3, a4, a5, a6 = st.columns(6)
        a1.metric("ACTIVE-V2 Sample", str(autopsy_summary.get("trades", 0)))
        a2.metric("Win Rate", f"{_float(autopsy_summary.get('win_rate')) * 100:.1f}%")
        a3.metric("Expectancy", _money(autopsy_summary.get("expectancy")))
        a4.metric("Profit Factor", f"{_float(autopsy_summary.get('profit_factor')):.2f}")
        a5.metric("Average Win", _money(autopsy_summary.get("average_win")))
        a6.metric("Average Loss", _money(autopsy_summary.get("average_loss")))
        st.markdown(
            f"<div class='small-note'>Champion: <strong>{escape(str(autopsy_registry.get('champion_version') or '—'))}</strong> · "
            f"Challenger: <strong>{escape(str(autopsy_registry.get('challenger_version') or '—'))}</strong> · "
            f"State: <strong>{escape(str(autopsy_registry.get('state') or 'OBSERVING'))}</strong> · "
            f"Promotion: <strong>{escape(str(autopsy_registry.get('promotion_status') or 'NOT_PROMOTED'))}</strong> · "
            f"Requirement: {escape(str(autopsy_registry.get('promotion_requirement') or '—'))}</div>",
            unsafe_allow_html=True,
        )
    telemetry = {}
    learning_db = Path("var/kalshi/research.db")
    if learning_db.exists():
        try:
            with sqlite3.connect(learning_db) as conn:
                telemetry = {
                    "kalshi": conn.execute("SELECT COUNT(*) FROM kalshi_observations").fetchone()[0],
                    "features": conn.execute("SELECT COUNT(*) FROM kalshi_learning_features").fetchone()[0],
                    "cross": conn.execute("SELECT COUNT(*) FROM kalshi_cross_market_samples").fetchone()[0],
                    "resolved": conn.execute("SELECT COUNT(*) FROM kalshi_resolutions WHERE result IN ('yes','no')").fetchone()[0],
                }
        except sqlite3.Error:
            telemetry = {}
    status_path = Path("var/global-intelligence/learning-status.json")
    if status_path.exists():
        try:
            telemetry.update(json.loads(status_path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    st.markdown("<div class='section-title'>Learning Command Center</div>", unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Kalshi Observations", str(telemetry.get("kalshi", 0)))
    c2.metric("Derived Features", str(telemetry.get("features", 0)))
    c3.metric("Cross-Market Samples", str(telemetry.get("cross", 0)))
    c4.metric("Resolved Markets", str(telemetry.get("resolved", 0)))
    c5.metric("Evidence State", str(telemetry.get("evidence_state", "COLLECTING_EVIDENCE")))
    funnel = [
        ("Kalshi Observations", telemetry.get("kalshi", 0)),
        ("Derived Features", telemetry.get("features", 0)),
        ("Cross-Market Samples", telemetry.get("cross", 0)),
        ("Lead/Lag Samples", telemetry.get("lead_lag", 0)),
        ("Validated Relationships", 0),
        ("Shadow Models", 0),
        ("Challengers", 0),
        ("Promotions", 0),
    ]
    st.markdown(
        "<div class='panel' style='padding:1rem'><strong>LEARNING FUNNEL</strong><br>"
        + " <span style='font-size:1.1rem'> ↓ </span> ".join(
            f"{escape(label)} <strong>{int(_float(value))}</strong>" for label, value in funnel
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div class='panel' style='padding:1rem'><strong>KALSHI LEARNING</strong><br>"
        f"Prediction and Perps histories are reprocessed from durable observations. "
        f"Calibration: <strong>{escape(str(telemetry.get('calibration', 'COLLECTING EVIDENCE')))}</strong> · "
        f"Last update: <strong>{escape(str(telemetry.get('recorded_at', '—')))}</strong><br>"
        "All derived features remain RESEARCH_ONLY with weight 0 and broker control false. "
        "Cross-market relationships and calibration remain collecting evidence until sufficient timestamp-aligned or resolved samples exist.</div>",
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
    perps_enabled = None
    if kalshi_db.exists():
        try:
            with sqlite3.connect(kalshi_db) as conn:
                kalshi_counts = dict(conn.execute("SELECT family, COUNT(*) FROM kalshi_observations GROUP BY family").fetchall())
                row = conn.execute("SELECT MAX(retrieved_at) FROM kalshi_observations").fetchone()
                kalshi_last = row[0] or kalshi_last
                enabled_row = conn.execute("SELECT payload_json FROM kalshi_observations WHERE family='perps' AND observation_type='enabled' ORDER BY retrieved_at DESC LIMIT 1").fetchone()
                if enabled_row:
                    perps_enabled = bool(json.loads(enabled_row[0]).get("enabled"))
        except sqlite3.Error:
            pass
    kalshi = {
        "Authentication": "CONNECTED" if os.getenv("KALSHI_API_KEY_ID") and os.getenv("KALSHI_PRIVATE_KEY_PATH") else "NOT CONFIGURED",
        "Predictions REST": "CONNECTED",
        "Predictions WebSocket": "NOT ACTIVE",
        "Perps REST": "EXTERNAL BLOCK" if perps_enabled is False else ("CONNECTED" if kalshi_counts.get("perps", 0) else "DEGRADED"),
        "Perps WebSocket": "NOT ACTIVE",
        "Records ingested": str(sum(kalshi_counts.values())),
        "Prediction markets tracked": str(kalshi_counts.get("predictions", 0)),
        "Perps instruments tracked": str(kalshi_counts.get("perps", 0)),
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


def _render_autonomous_lab_view(ctx: dict[str, object]) -> None:
    """Display the authoritative paper-lab evidence without inventing values."""
    st.markdown("## AUTONOMOUS TRADING LAB")
    report = _safe_json(Path("var/reports/overnight-forward-campaign.json"))
    daily = _safe_json(Path(f"var/reports/daily-learning-{datetime.now(UTC).date().isoformat()}.json"))
    daily_activity = daily.get("activity") if isinstance(daily.get("activity"), dict) else {}
    shadow_by_pillar = daily.get("shadow_by_pillar") if isinstance(daily.get("shadow_by_pillar"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    st.caption(
        f"MODE: {safety.get('mode', 'UNKNOWN')} · LIVE_TRADING_ENABLED: {safety.get('live_trading_enabled', 'UNKNOWN')} · "
        f"REAL-MONEY ORDERS: {safety.get('real_money_orders', 'UNKNOWN')} · EVIDENCE: {report.get('evidence_policy', 'UNKNOWN')}"
    )
    engines = report.get("engines") if isinstance(report.get("engines"), dict) else {}
    providers = report.get("providers") if isinstance(report.get("providers"), dict) else {}
    pillar_performance = ctx.get("pillar_performance") if isinstance(ctx.get("pillar_performance"), dict) else {}
    live_pillar_status = ctx.get("live_pillar_status") if isinstance(ctx.get("live_pillar_status"), dict) else {}
    rows = []
    for name in ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps"):
        values = engines.get(name) if isinstance(engines.get(name), dict) else {}
        daily_values = daily_activity.get(name) if isinstance(daily_activity.get(name), dict) else {}
        provider = providers.get(name) if name in {"Kalshi Predictions", "Kalshi Perps"} and isinstance(providers.get(name), dict) else {}
        provider_funnel = provider.get("funnel") if isinstance(provider.get("funnel"), dict) else {}
        is_kalshi = bool(provider)
        session_evidence = values.get("session_evidence") if isinstance(values.get("session_evidence"), dict) else {}
        status = session_evidence.get("status") or ("ACTIVE" if values.get("latest") not in (None, "UNKNOWN") else "UNKNOWN")
        if is_kalshi:
            status = provider.get("state", "UNKNOWN")
        shadow_values = shadow_by_pillar.get(name) if isinstance(shadow_by_pillar.get(name), dict) else {}
        accounting_name = {"Stocks": "US Stocks / ETFs", "Metals": "Metals / Commodities", "Kalshi Predictions": "Kalshi", "Kalshi Perps": "Kalshi"}.get(name, name)
        actual_values = pillar_performance.get(accounting_name) if isinstance(pillar_performance.get(accounting_name), dict) else {}
        actual_provider = live_pillar_status.get(accounting_name) if isinstance(live_pillar_status.get(accounting_name), dict) else {}
        actual_expectancy = actual_values.get("expectancy", "UNKNOWN")
        realized_pnl = actual_values.get("realized_pnl", actual_values.get("net_generated_cash", "UNKNOWN"))
        open_actual = actual_provider.get("positions", "UNKNOWN")
        bottlenecks = daily_values.get("bottlenecks") if isinstance(daily_values.get("bottlenecks"), list) else []
        top_bottleneck = bottlenecks[0] if bottlenecks else (daily_values.get("top_bottlenecks") or "UNKNOWN")
        provider_health = "UNKNOWN"
        if is_kalshi:
            health_components = (
                bool(provider.get("observed_at")),
                bool(provider.get("cycle_count")),
                bool(provider.get("markets", provider.get("instruments"))),
                bool(provider_funnel),
                True,
                True,
            )
            provider_health = round(sum(health_components) * 100 / len(health_components))
        rows.append({"Engine": name, "Status": status, "Activity Health": provider_health if is_kalshi else values.get("activity_health", "UNKNOWN"), "Last Cycle": provider.get("observed_at", values.get("latest", "UNKNOWN")), "Markets Scanned": provider.get("markets", provider.get("instruments", values.get("observations", "UNKNOWN"))), "Strategy Evaluations": daily_values.get("observations", "UNKNOWN"), "Candidates": provider_funnel.get("scanned", daily_values.get("candidates", "UNKNOWN")) if is_kalshi else daily_values.get("candidates", "UNKNOWN"), "Signals": values.get("signals", daily_values.get("signals", "UNKNOWN")), "Positive Edge/Proxy": provider_funnel.get("positive_edge", "UNKNOWN") if is_kalshi else "UNKNOWN", "Qualified": provider_funnel.get("qualified", values.get("qualified", daily_values.get("qualified", "UNKNOWN"))) if is_kalshi else values.get("qualified", daily_values.get("qualified", "UNKNOWN")), "Actual Orders": provider.get("orders", "UNKNOWN") if is_kalshi else "UNKNOWN", "Shadow Trades": shadow_values.get("entries", "UNKNOWN"), "Fills": provider.get("fills", "UNKNOWN") if is_kalshi else "UNKNOWN", "Open Actual": open_actual, "Open Shadow": (shadow_values.get("entries", 0) - shadow_values.get("completed", 0)) if shadow_values else "UNKNOWN", "Actual Exits": actual_values.get("completed_trades", "UNKNOWN"), "Shadow Exits": shadow_values.get("completed", "UNKNOWN"), "Actual Expectancy": actual_expectancy, "Shadow Expectancy": shadow_values.get("hypothetical_expectancy", "UNKNOWN"), "Realized P&L": realized_pnl, "Unrealized P&L": provider.get("unrealized_pnl", actual_provider.get("unrealized_pnl", "UNKNOWN")) if is_kalshi else actual_provider.get("unrealized_pnl", "UNKNOWN"), "Learning Observations": daily_values.get("observations", "UNKNOWN"), "Top Bottleneck": top_bottleneck, "Regime": (next(iter((daily_values.get("regimes") or {}).keys()), "UNKNOWN"))})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.markdown("### Provider health")
    provider_rows = []
    provider_jobs = {
        "Alpaca": {"autonomous-paper-trading", "alpaca-metals-paper-trading", "crypto-market-data-archive"},
        "OANDA": {"oanda-fx-paper-trading"},
        "Saxo": {"saxo-international-paper-trading"},
    }
    runtime_metrics = {name: [] for name in provider_jobs}
    try:
        with sqlite3.connect("var/autotrader/audit.db") as connection:
            audit_rows = connection.execute(
                "SELECT data_json, created_at FROM audit_events "
                "WHERE event_type = 'runtime_job' AND created_at >= ?",
                ((datetime.now(UTC) - timedelta(hours=24)).isoformat(),),
            ).fetchall()
        for raw, created_at in audit_rows:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for name, jobs in provider_jobs.items():
                if data.get("job") in jobs:
                    runtime_metrics[name].append((data, created_at))
    except sqlite3.Error:
        pass
    for name, entries in runtime_metrics.items():
        durations = sorted(float(data["duration_ms"]) for data, _ in entries if data.get("duration_ms") is not None)
        failures = sum(data.get("ok") is False for data, _ in entries)
        successes = [created_at for data, created_at in entries if data.get("ok") is True]
        provider_rows.append({
            "Provider": name,
            "Status": "CONNECTED" if successes else ("DEGRADED" if entries else "UNKNOWN"),
            "Last successful call": max(successes, default="UNKNOWN"),
            "Requests (job proxy)": len(entries) if entries else "UNKNOWN",
            "Failures": failures if entries else "UNKNOWN",
            "Timeouts": "UNKNOWN",
            "Retries": "UNKNOWN",
            "Measurement scope": "runtime_job_proxy",
            "p50 latency ms (job proxy)": durations[(len(durations) - 1) // 2] if durations else "UNKNOWN",
            "p95 latency ms (job proxy)": durations[max(0, (len(durations) * 95 + 99) // 100 - 1)] if durations else "UNKNOWN",
        })
    for name in ("Kalshi",):
        prediction = providers.get("Kalshi Predictions") if isinstance(providers.get("Kalshi Predictions"), dict) else {}
        perps = providers.get("Kalshi Perps") if isinstance(providers.get("Kalshi Perps"), dict) else {}
        timestamps = [v.get("latest_observed_at") for v in (prediction, perps) if v.get("latest_observed_at") not in (None, "UNKNOWN")]
        telemetry = [v.get("provider_telemetry") for v in (prediction, perps) if isinstance(v.get("provider_telemetry"), dict)]
        requests = sum(int(v.get("requests", 0) or 0) for v in telemetry) if telemetry else "UNKNOWN"
        failures = sum(int(v.get("failures", 0) or 0) for v in telemetry) if telemetry else "UNKNOWN"
        timeouts = sum(int(v.get("timeouts", 0) or 0) for v in telemetry) if telemetry else "UNKNOWN"
        retries = sum(int(v.get("retries", 0) or 0) for v in telemetry) if telemetry else "UNKNOWN"
        p50 = [float(v["p50_latency_ms"]) for v in telemetry if v.get("p50_latency_ms") is not None]
        p95 = [float(v["p95_latency_ms"]) for v in telemetry if v.get("p95_latency_ms") is not None]
        provider_rows.append({
            "Provider": name,
            "Status": "CONNECTED" if any(v.get("state") == "SCANNING" for v in (prediction, perps)) else "UNKNOWN",
            "Last successful call": max(timestamps, default="UNKNOWN"),
            "Requests (latest cycle)": requests, "Failures": failures, "Timeouts": timeouts, "Retries": retries,
            "p50 latency ms (latest cycle)": min(p50) if p50 else "UNKNOWN",
            "p95 latency ms (latest cycle)": max(p95) if p95 else "UNKNOWN",
        })
    st.dataframe(provider_rows, use_container_width=True, hide_index=True)
    st.markdown("### Kalshi candidate telemetry")
    telemetry_rows = []
    for family in ("predictions", "perps"):
        telemetry_path = Path("var/kalshi") / f"candidate-telemetry-{family}.jsonl"
        records = []
        if telemetry_path.exists():
            try:
                records = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except (OSError, json.JSONDecodeError):
                records = []
        latest = records[-1] if records and isinstance(records[-1], dict) else {}
        telemetry_rows.append({
            "Engine": f"Kalshi {family.title()}",
            "Candidate records": len(records) if records else "UNKNOWN",
            "Latest observation": latest.get("observed_at", "UNKNOWN"),
            "Qualified": latest.get("qualification", "UNKNOWN"),
            "Rejection": latest.get("rejection", "UNKNOWN"),
            "Calibrated edge": latest.get("estimated_edge", "UNKNOWN"),
            "Calibrated EV": latest.get("expected_value", "UNKNOWN"),
        })
    st.dataframe(telemetry_rows, use_container_width=True, hide_index=True)
    shadow = report.get("shadow") if isinstance(report.get("shadow"), dict) else {}
    cols = st.columns(4)
    for col, label, key in zip(cols, ("Shadow Entries", "Shadow Exits", "Completed Shadow P&L", "Daily Observations"), ("entries", "exits", "completed_pnl", "observations"), strict=True):
        value = shadow.get(key, daily.get("shadow_results", {}).get("entries", "UNKNOWN") if key == "observations" else "UNKNOWN")
        col.metric(label, value)
    st.markdown("### Evidence limitations")
    limitations = daily.get("evidence_limitations", [])
    st.write(limitations if limitations else ["UNKNOWN"])
    st.markdown("### Strategy leaderboard")
    registry = _safe_json(Path("var/reports/strategy-registry-v1.json"))
    definitions = {
        item.get("strategy_id"): item
        for item in registry.get("definitions", [])
        if isinstance(item, dict) and item.get("strategy_id")
    }
    shadow_scorecards = {}
    shadow_regimes = {}
    experiment_db = Path("var/autotrader/paper_experiment.db")
    if experiment_db.exists():
        try:
            with sqlite3.connect(experiment_db) as connection:
                for strategy_id, completed, wins, losses, pnl in connection.execute(
                    "SELECT strategy_id, COUNT(*), SUM(result='WIN'), SUM(result='LOSS'), SUM(hypothetical_pnl) "
                    "FROM shadow_trades WHERE exit_at IS NOT NULL GROUP BY strategy_id"
                ):
                    shadow_scorecards[strategy_id] = {"completed": completed, "wins": wins or 0, "losses": losses or 0, "pnl": pnl or 0.0, "expectancy": (pnl or 0.0) / completed if completed else "UNKNOWN"}
                for strategy_id, regime, completed, pnl in connection.execute(
                    "SELECT strategy_id, regime, COUNT(*), SUM(hypothetical_pnl) FROM shadow_trades "
                    "WHERE exit_at IS NOT NULL AND regime IS NOT NULL GROUP BY strategy_id, regime"
                ):
                    if completed:
                        shadow_regimes.setdefault(strategy_id, {})[regime] = (pnl or 0.0) / completed
        except sqlite3.Error:
            shadow_scorecards = {}
    leaderboard = []
    for scorecard in registry.get("scorecards", []):
        if not isinstance(scorecard, dict):
            continue
        definition = definitions.get(scorecard.get("strategy_id"), {})
        observations = scorecard.get("observations", 0)
        shadow = shadow_scorecards.get(scorecard.get("strategy_id"), {})
        regimes = shadow_regimes.get(scorecard.get("strategy_id"), {})
        best_regime = max(regimes, key=regimes.get) if regimes else "UNKNOWN"
        worst_regime = min(regimes, key=regimes.get) if regimes else "UNKNOWN"
        leaderboard.append({
            "Strategy": scorecard.get("strategy_id", "UNKNOWN"),
            "Pillar": definition.get("pillar", "UNKNOWN"),
            "Status": definition.get("status", "UNKNOWN"),
            "Observations": observations,
            "Completed Trades": scorecard.get("trades", "UNKNOWN"),
            "Expectancy": scorecard.get("expectancy", "UNKNOWN"),
            "Profit Factor": scorecard.get("profit_factor", "UNKNOWN"),
            "Drawdown": scorecard.get("max_drawdown", "UNKNOWN"),
            "Shadow Completed": shadow.get("completed", "UNKNOWN"),
            "Shadow Wins": shadow.get("wins", "UNKNOWN"),
            "Shadow Losses": shadow.get("losses", "UNKNOWN"),
            "Shadow Expectancy": shadow.get("expectancy", "UNKNOWN"),
            "Shadow P&L": shadow.get("pnl", "UNKNOWN"),
            "Sample classification": "INSUFFICIENT_EVIDENCE" if not isinstance(observations, int) or observations < definition.get("minimum_sample_size", 30) else "EARLY_SIGNAL",
            "Best regime": best_regime,
            "Worst regime": worst_regime,
        })
    st.dataframe(leaderboard or [{"Strategy": "UNKNOWN"}], use_container_width=True, hide_index=True)


def render_dashboard() -> None:
    last_refreshed = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.session_state["dashboard_last_refreshed"] = last_refreshed
    st.markdown(_dashboard_css(), unsafe_allow_html=True)
    st.sidebar.markdown(
        """
        <div class="brand-box">
          <div class="brand-mark">CH</div>
          <div class="brand-name">Chris Haake<br>Capital Systems</div>
        <div class="brand-sub">SIX-PILLAR AUTONOMOUS SYSTEM</div>
        <div class="brand-sub">Christopher J. Haake</div>
        <div class="brand-footer">Research. Discipline. Execution.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    auto_refresh = st.sidebar.toggle("Auto Refresh", value=bool(st.session_state.get("dashboard_auto_refresh", False)))
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
        fetch_live_broker_data.clear()
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
            "AUTONOMOUS LAB",
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
    elif selected_view == "AUTONOMOUS LAB":
        _render_autonomous_lab_view(ctx)
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
