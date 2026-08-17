from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_portfolio(path: Path) -> tuple[dict[str, object], list[dict[str, object]], int]:
    if not path.exists():
        return {}, [], 0
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        state = conn.execute("SELECT * FROM portfolio_state WHERE id = 1").fetchone()
        positions = [dict(row) for row in conn.execute("SELECT * FROM positions ORDER BY symbol")]
        try:
            fill_count = int(conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"])
        except sqlite3.Error:
            fill_count = 0
    return ({} if state is None else dict(state), positions, fill_count)


def read_activity(path: Path, limit: int = 40) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = []
        for table in ("audit_events", "events"):
            try:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
                break
            except sqlite3.Error:
                continue
    result: list[dict[str, object]] = []
    for row in rows:
        record = dict(row)
        result.append(
            {
                "time": record.get("created_at") or record.get("timestamp") or record.get("occurred_at"),
                "event": record.get("event_type") or record.get("type") or "event",
                "message": record.get("message") or "",
            }
        )
    return result


def broker_for_symbol(symbol: str, asset_class: str | None) -> str:
    if (asset_class or "").lower() == "forex" or "/" in symbol:
        return "OANDA Practice"
    return "Alpaca Paper"


def build_snapshot(status_path: Path, ledger_path: Path, audit_path: Path) -> dict[str, object]:
    status = read_json(status_path)
    state, positions, fill_count = read_portfolio(ledger_path)
    jobs = status.get("jobs") if isinstance(status.get("jobs"), dict) else {}
    auto = jobs.get("autonomous-paper-trading") if isinstance(jobs, dict) else {}
    if not isinstance(auto, dict):
        auto = {}

    equity = float(state.get("equity", 2000.0) or 2000.0)
    peak = float(state.get("peak_equity", equity) or equity)
    drawdown = max((peak - equity) / peak, 0.0) if peak > 0 else 0.0
    last_heartbeat = status.get("last_heartbeat_at")

    healthy = bool(last_heartbeat) and not bool(auto.get("disabled")) and not bool(auto.get("last_error"))

    safe_positions = []
    for row in positions:
        symbol = str(row.get("symbol") or "")
        asset_class = str(row.get("asset_class") or "")
        safe_positions.append(
            {
                "broker": broker_for_symbol(symbol, asset_class),
                "symbol": symbol,
                "asset_class": asset_class,
                "quantity": row.get("quantity"),
                "average_price": row.get("average_price"),
                "stop_price": row.get("stop_price"),
            }
        )

    return {
        "published_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "mode": status.get("mode", "paper"),
            "healthy": healthy,
            "last_heartbeat_at": last_heartbeat,
            "autonomous_job_disabled": bool(auto.get("disabled", False)),
            "consecutive_failures": int(auto.get("consecutive_failures", 0) or 0),
            "last_error": auto.get("last_error"),
        },
        "portfolio": {
            "equity": equity,
            "daily_pnl": float(state.get("daily_pnl", 0.0) or 0.0),
            "weekly_pnl": float(state.get("weekly_pnl", 0.0) or 0.0),
            "drawdown_pct": drawdown,
        },
        "guardrails": {
            "risk_per_trade_pct": 0.0125,
            "max_daily_loss_pct": 0.05,
            "max_peak_drawdown_pct": 0.15,
        },
        "fill_count": fill_count,
        "positions": safe_positions,
        "activity": read_activity(audit_path),
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
    print(json.dumps({"output": str(output), "published_at": snapshot["published_at"], "runtime": snapshot["runtime"]}, indent=2))


if __name__ == "__main__":
    main()
