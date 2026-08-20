from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from autotrader.brokers.alpaca_metals_paper import METALS_UNIVERSE
from autotrader.brokers.safety import alpaca_open_positions, oanda_open_positions
from autotrader.capital_allocations import TOTAL_PAPER_CAPITAL
from autotrader.cash_dashboard import aggregate_cash_dashboard
from autotrader.coordinated_test import FivePillarTestConfig, five_pillar_performance


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_portfolio(
    path: Path,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    if not path.exists():
        return {}, [], [], []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        state = conn.execute("SELECT * FROM portfolio_state WHERE id = 1").fetchone()
        positions = [dict(row) for row in conn.execute("SELECT * FROM positions ORDER BY symbol")]
        try:
            fills = [dict(row) for row in conn.execute("SELECT * FROM fills ORDER BY occurred_at")]
        except sqlite3.Error:
            fills = []
        pillar_trades = []
        for table in ("international_trades", "metals_trades"):
            try:
                pillar_trades.extend(
                    dict(row)
                    for row in conn.execute(f"SELECT * FROM {table} WHERE status = 'closed' ORDER BY closed_at")
                )
            except sqlite3.Error:
                continue
    return ({} if state is None else dict(state), positions, fills, pillar_trades)


def read_activity(path: Path, limit: int = 50) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not path.exists():
        return [], {}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = []
        for table in ("audit_events", "events"):
            try:
                rows = conn.execute(
                    f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                break
            except sqlite3.Error:
                continue

    result: list[dict[str, object]] = []
    latest_cycle: dict[str, object] = {}
    for row in rows:
        record = dict(row)
        data = {}
        raw = record.get("data_json")
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except Exception:
                data = {}
        message = str(record.get("message") or "")
        result.append(
            {
                "time": record.get("created_at") or record.get("timestamp") or record.get("occurred_at"),
                "event": record.get("event_type") or record.get("type") or "event",
                "message": message,
            }
        )
        if not latest_cycle and "Autonomous paper cycle" in message:
            latest_cycle = {
                "time": record.get("created_at") or record.get("timestamp") or record.get("occurred_at"),
                "message": message,
                **data,
            }
    return result, latest_cycle


def ledger_stop_map(rows: list[dict[str, object]]) -> dict[str, float]:
    return {str(row.get("symbol") or ""): _float(row.get("stop_price")) for row in rows}


def live_broker_positions(ledger_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, float]]:
    stops = ledger_stop_map(ledger_rows)
    positions: list[dict[str, object]] = []
    metrics = {
        "unrealized_pnl": 0.0,
        "gross_exposure": 0.0,
        "alpaca_exposure": 0.0,
        "metals_exposure": 0.0,
        "oanda_exposure": 0.0,
    }

    try:
        raw_alpaca = alpaca_open_positions().details.get("positions", [])
    except Exception:
        raw_alpaca = []
    if isinstance(raw_alpaca, list):
        for row in raw_alpaca:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            qty = _float(row.get("qty"))
            avg = _float(row.get("avg_entry_price"))
            current = _float(row.get("current_price"), avg)
            market_value = abs(_float(row.get("market_value"), qty * current))
            unrealized = _float(row.get("unrealized_pl"))
            stop = stops.get(symbol, 0.0)
            risk_dollars = max((avg - stop) * max(qty, 0.0), 0.0) if stop else 0.0
            is_metal = symbol.upper() in METALS_UNIVERSE
            positions.append(
                {
                    "pillar": "Metals/Commodities" if is_metal else "Stocks/Crypto",
                    "broker": "Alpaca Paper",
                    "symbol": symbol,
                    "asset_class": "us_equity",
                    "quantity": qty,
                    "average_price": avg,
                    "current_price": current,
                    "stop_price": stop or None,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized,
                    "unrealized_pct": _float(row.get("unrealized_plpc")),
                    "risk_dollars": risk_dollars,
                }
            )
            metrics["unrealized_pnl"] += unrealized
            metrics["gross_exposure"] += market_value
            metrics["alpaca_exposure"] += market_value
            if is_metal:
                metrics["metals_exposure"] += market_value

    try:
        raw_oanda = oanda_open_positions().details.get("positions", [])
    except Exception:
        raw_oanda = []
    if isinstance(raw_oanda, list):
        for row in raw_oanda:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("instrument") or "").replace("_", "/")
            long = row.get("long") if isinstance(row.get("long"), dict) else {}
            short = row.get("short") if isinstance(row.get("short"), dict) else {}
            long_units = _float(long.get("units"))
            short_units = _float(short.get("units"))
            qty = long_units + short_units
            side = long if abs(long_units) >= abs(short_units) else short
            avg = _float(side.get("averagePrice"))
            unrealized = _float(row.get("unrealizedPL"))
            stop = stops.get(symbol, 0.0)
            exposure = abs(qty * avg)
            risk_dollars = abs(avg - stop) * abs(qty) if stop and avg else 0.0
            positions.append(
                {
                    "broker": "OANDA Practice",
                    "symbol": symbol,
                    "asset_class": "forex",
                    "quantity": qty,
                    "average_price": avg,
                    "current_price": None,
                    "stop_price": stop or None,
                    "market_value": exposure,
                    "unrealized_pnl": unrealized,
                    "unrealized_pct": None,
                    "risk_dollars": risk_dollars,
                }
            )
            metrics["unrealized_pnl"] += unrealized
            metrics["gross_exposure"] += exposure
            metrics["oanda_exposure"] += exposure

    return positions, metrics


def build_snapshot(status_path: Path, ledger_path: Path, audit_path: Path) -> dict[str, object]:
    status = read_json(status_path)
    state, ledger_positions, fills, pillar_trades = read_portfolio(ledger_path)
    activity, latest_cycle = read_activity(audit_path)
    live_positions, broker_metrics = live_broker_positions(ledger_positions)

    jobs = status.get("jobs") if isinstance(status.get("jobs"), dict) else {}
    auto = jobs.get("autonomous-paper-trading") if isinstance(jobs, dict) else {}
    if not isinstance(auto, dict):
        auto = {}

    base_equity = TOTAL_PAPER_CAPITAL
    peak = max(_float(state.get("peak_equity"), base_equity), base_equity)
    open_pnl = broker_metrics["unrealized_pnl"]
    marked_equity = base_equity + open_pnl
    drawdown = max((peak - marked_equity) / peak, 0.0) if peak > 0 else 0.0
    gross_exposure = broker_metrics["gross_exposure"]
    risk_open = sum(_float(row.get("risk_dollars")) for row in live_positions)
    last_heartbeat = status.get("last_heartbeat_at")
    healthy = bool(last_heartbeat) and not bool(auto.get("disabled")) and not bool(auto.get("last_error"))

    stretch_low = 0.20
    stretch_high = 0.30
    mtm_return = (marked_equity - base_equity) / base_equity if base_equity > 0 else 0.0
    realized_records = [*fills, *pillar_trades]
    cash_preview = aggregate_cash_dashboard(
        realized_records=realized_records,
        positions=live_positions,
        available_cash=0.0,
        original_capital=TOTAL_PAPER_CAPITAL,
    )
    internal_available_cash = max(
        TOTAL_PAPER_CAPITAL
        + cash_preview.net_trading_cash_generated
        - cash_preview.capital_deployed
        - cash_preview.protected_cash_reserve,
        0.0,
    )
    cash_dashboard = aggregate_cash_dashboard(
        realized_records=realized_records,
        positions=live_positions,
        available_cash=internal_available_cash,
        original_capital=TOTAL_PAPER_CAPITAL,
    )
    pillar_performance = five_pillar_performance(
        completed_trades=realized_records,
        positions=live_positions,
    )

    return {
        "published_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "mode": status.get("mode", "paper"),
            "healthy": healthy,
            "last_heartbeat_at": last_heartbeat,
            # Missing/unreadable runtime state must display as disarmed, never enabled.
            "autonomous_job_disabled": bool(auto.get("disabled", True)),
            "consecutive_failures": int(auto.get("consecutive_failures", 0) or 0),
            "last_error": auto.get("last_error"),
            "last_cycle_started_at": auto.get("last_started_at"),
            "last_cycle_finished_at": auto.get("last_finished_at"),
            "last_cycle_duration_ms": auto.get("last_duration_ms"),
        },
        "portfolio": {
            "base_equity": base_equity,
            "marked_equity": marked_equity,
            "open_unrealized_pnl": open_pnl,
            "mtm_return_pct": mtm_return,
            "drawdown_pct": drawdown,
            "gross_exposure": gross_exposure,
            "open_risk_dollars": risk_open,
            "alpaca_exposure": broker_metrics["alpaca_exposure"],
            "metals_exposure": broker_metrics["metals_exposure"],
            "oanda_exposure": broker_metrics["oanda_exposure"],
        },
        "targets": {
            "stretch_daily_low_pct": stretch_low,
            "stretch_daily_high_pct": stretch_high,
            "progress_to_low": mtm_return / stretch_low if stretch_low else 0.0,
            "progress_to_high": mtm_return / stretch_high if stretch_high else 0.0,
            "note": "Stretch benchmark only; the trader does not force trades to hit it.",
        },
        "guardrails": {
            "risk_per_trade_pct": 0.0125,
            "max_daily_loss_pct": 0.05,
            "max_peak_drawdown_pct": 0.15,
        },
        "cash_dashboard": cash_dashboard.as_dict(),
        "coordinated_test": FivePillarTestConfig().as_dict(),
        "pillar_performance": pillar_performance,
        "fill_count": len(fills),
        "positions": live_positions,
        "latest_cycle": latest_cycle,
        "activity": activity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish sanitized VM state for the Streamlit dashboard")
    parser.add_argument("--status", default="var/autotrader/status.json")
    parser.add_argument("--ledger", default="var/autotrader/portfolio.db")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    parser.add_argument("--output", default="dashboard/data.json")
    args = parser.parse_args()

    snapshot = build_snapshot(Path(args.status), Path(args.ledger), Path(args.audit_db))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output), "published_at": snapshot["published_at"], "runtime": snapshot["runtime"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
