#!/usr/bin/env python3
"""Create a truthful, timestamped performance baseline for the paper lab.

The baseline intentionally reports ``UNKNOWN`` when a metric is not persisted
by the current architecture; it never derives historical performance from
unverified provider inventory.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

PILLARS = {
    "Stocks": ("Stocks", "alpaca_equities"),
    "Crypto": ("Crypto", "alpaca_crypto"),
    "Forex": ("Forex", "oanda_fx"),
    "Metals": ("Metals", "alpaca_metals"),
    "International": ("International", "ibkr_global"),
}

CANONICAL_PROVIDERS = {
    "Stocks": "Alpaca Paper",
    "Crypto": "Alpaca Paper",
    "Forex": "OANDA Practice",
    "Metals": "Alpaca Paper",
    "International": "Saxo SIM",
}


def _sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _runtime_status() -> dict[str, object]:
    try:
        return json.loads(Path("var/autotrader/status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pillar_rows() -> dict[str, dict[str, object]]:
    connection = sqlite3.connect("var/autotrader/portfolio.db")
    connection.row_factory = sqlite3.Row
    rows: dict[str, dict[str, object]] = {}
    for pillar, (accounting_key, _) in PILLARS.items():
        snapshot = connection.execute(
            "SELECT * FROM pillar_accounting_snapshot WHERE pillar=?", (accounting_key,)
        ).fetchone()
        if snapshot is None:
            rows[pillar] = {"allocated_capital": 1000.0, "source": "no snapshot", "status": "UNKNOWN"}
            continue
        data = dict(snapshot)
        rows[pillar] = {
            "execution_provider": CANONICAL_PROVIDERS[pillar],
            "allocated_capital": data.get("allocation_cap"),
            "current_equity": data.get("economic_equity"),
            "available_capital": data.get("available_cash"),
            "deployed_capital": data.get("deployed_cash"),
            "positions": data.get("positions"),
            "working_orders": data.get("working_orders"),
            "realized_pnl": data.get("realized_today"),
            "unrealized_pnl": data.get("unrealized"),
            "accounting_status": data.get("accounting_status"),
            "observed_at": data.get("observed_at"),
        }
    connection.close()
    return rows


def _trade_metrics() -> dict[str, dict[str, object]]:
    connection = sqlite3.connect("var/autotrader/portfolio.db")
    connection.row_factory = sqlite3.Row
    result: dict[str, dict[str, object]] = {}
    for pillar, (_, manifest_key) in PILLARS.items():
        symbols = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT canonical_symbol FROM entry_manifests WHERE pillar=? AND canonical_symbol IS NOT NULL",
                (manifest_key,),
            ).fetchall()
        ]
        fills = []
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            fills = connection.execute(
                f"SELECT side, realized_pnl FROM fills WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
        result[pillar] = {
            "fills": len(fills),
            "completed_trades": "UNKNOWN",
            "wins": "UNKNOWN",
            "losses": "UNKNOWN",
            "breakeven_trades": "UNKNOWN",
            "win_rate": "UNKNOWN",
            "average_win": "UNKNOWN",
            "average_loss": "UNKNOWN",
            "profit_factor": "UNKNOWN",
            "expectancy_per_trade": "UNKNOWN",
            "maximum_drawdown": "UNKNOWN",
            "average_holding_time": "UNKNOWN",
            "turnover": "UNKNOWN",
        }
    connection.close()
    return result


def main() -> None:
    observed_at = datetime.now(UTC).isoformat()
    status = _runtime_status()
    baseline = {
        "baseline_id": "PERFORMANCE_BASELINE_V1",
        "created_at": observed_at,
        "git_sha": _sha(),
        "mode": status.get("mode", "UNKNOWN"),
        "live_trading_enabled": status.get("live_trading_enabled", "UNKNOWN"),
        "pillars": _pillar_rows(),
        "trade_metrics": _trade_metrics(),
        "kalshi": {
            "predictions": json.loads(Path("var/kalshi/execution-predictions.json").read_text())
            if Path("var/kalshi/execution-predictions.json").exists() else "UNKNOWN",
            "perps": json.loads(Path("var/kalshi/execution-perps.json").read_text())
            if Path("var/kalshi/execution-perps.json").exists() else "UNKNOWN",
        },
        "activity_metrics": {
            "candidate_count": "UNKNOWN",
            "qualified_signal_count": "UNKNOWN",
            "rejection_count": "UNKNOWN",
            "learning_observations": "UNKNOWN",
            "strategy_versions": "UNKNOWN",
        },
        "notes": [
            "Historical metrics unavailable from durable current schema remain UNKNOWN.",
            "Provider legacy inventory is not imported into current-fund economics.",
        ],
    }
    output = Path("var/reports/performance-baseline-v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(output), "baseline_id": baseline["baseline_id"], "git_sha": baseline["git_sha"], "created_at": observed_at}, sort_keys=True))


if __name__ == "__main__":
    main()
