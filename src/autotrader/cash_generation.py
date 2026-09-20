"""Forward-verified cash generation reporting and opportunity ranking.

This module is deliberately read-only with respect to execution.  It consumes
provider-linked lifecycle evidence and never turns marks or simulations into
realized cash.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping

from .forward_verification import ensure_verification_epoch


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def classify_manifest_record(row: Mapping[str, object], *, epoch_id: str | None = None,
                             epoch_started: str | None = None,
                             verification_epoch_id: str | None = None,
                             started_at: str | None = None) -> str:
    """Classify known pre-epoch fixture contamination without deleting history."""
    epoch_id = epoch_id or verification_epoch_id or ""
    epoch_started = epoch_started or started_at or ""
    timestamp = str(row.get("timestamp") or row.get("timestamp_utc") or "")
    is_old = False
    try:
        is_old = datetime.fromisoformat(timestamp.replace("Z", "+00:00")) < datetime.fromisoformat(epoch_started.replace("Z", "+00:00"))
    except ValueError:
        pass
    if is_old and (row.get("order_intent_id") in {"I2", "SPY"} or str(row.get("symbol", "")).upper() == "SPY"):
        return "PRE_EPOCH_TEST"
    if str(row.get("source", "")).lower() in {"test", "fixture", "pytest"}:
        return "TEST_FIXTURE"
    if str(row.get("verification_epoch_id")) != epoch_id:
        return "PRE_EPOCH_TEST"
    return "CURRENT_FORWARD"


def load_forward_events(path: str | Path = "var/autotrader/execution-manifest.jsonl") -> tuple[list[dict[str, object]], dict[str, int]]:
    epoch = ensure_verification_epoch()
    rows: list[dict[str, object]] = []
    contamination = {"TEST_FIXTURE": 0, "PRE_EPOCH_TEST": 0}
    p = Path(path)
    if not p.exists():
        return rows, contamination
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        category = classify_manifest_record(row, epoch_id=str(epoch["verification_epoch_id"]), epoch_started=str(epoch["started_at"]))
        if category != "CURRENT_FORWARD":
            contamination[category] = contamination.get(category, 0) + 1
            continue
        if row.get("ownership_classification") == "PLATFORM_OWNED_CURRENT_EXPERIMENT":
            rows.append(row)
    return rows, contamination


def _metrics(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    closed = [r for r in rows if r.get("event_type") == "POSITION_CLOSED"]
    realized = [_num(r.get("realized_pnl")) for r in closed]
    known = [x for x in realized if x is not None]
    wins = [x for x in known if x > 0]
    losses = [x for x in known if x < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return {"realized_cash_pnl": sum(known) if len(known) == len(closed) else ("UNKNOWN" if closed else 0.0), "gross_profit": gross_profit, "gross_loss": gross_loss,
            "wins": len(wins), "losses": len(losses), "closed_trades": len(closed),
            "profit_factor": (gross_profit / gross_loss if gross_loss else ("INF" if gross_profit else "UNKNOWN")),
            "expectancy": (sum(known) / len(known) if known and len(known) == len(closed) else "UNKNOWN"),
            "open_positions": max(sum(r.get("event_type") == "POSITION_OPENED" for r in rows) - sum(r.get("event_type") == "POSITION_CLOSED" for r in rows), 0)}


def write_cash_generation_reports(*, manifest_path: str | Path = "var/autotrader/execution-manifest.jsonl", report_dir: str | Path = "var/reports", now: datetime | None = None) -> tuple[Path, Path]:
    now = now or datetime.now(UTC)
    rows, contamination = load_forward_events(manifest_path)
    base = _metrics(rows)
    base.update({"date": now.date().isoformat(), "starting_forward_capital": 6000.0, "ending_forward_capital": "FROM_VERIFIED_LEDGER",
                 "unrealized_pnl": "FROM_PROVIDER_MARKS", "capital_turnover": "FROM_RESERVATION_LEDGER", "capital_velocity": "REQUIRES_DURATION_EVIDENCE",
                 "return_on_capital": "REQUIRES_VERIFIED_CAPITAL", "return_on_margin": "REQUIRES_MARGIN_EVIDENCE", "maximum_intraday_drawdown": "REQUIRES_EQUITY_CURVE",
                 "long_realized_pnl": "FROM_CLOSED_TRADE_SIDE", "short_realized_pnl": "FROM_CLOSED_TRADE_SIDE", "options_realized_pnl": "FROM_CLOSED_TRADE_PILLAR",
                 "forex_realized_pnl": "FROM_CLOSED_TRADE_PILLAR", "kalshi_realized_pnl": "FROM_CLOSED_TRADE_PILLAR", "strategy_leader": "INSUFFICIENT_SAMPLE",
                 "strategy_laggard": "INSUFFICIENT_SAMPLE", "income_target_progress": "CONFIGURE_TARGET_AND_SAMPLE", "verification_confidence": "HIGH" if base["closed_trades"] else "NO_FORWARD_EXECUTION",
                 "test_contamination": {"status": "ISOLATED", "counts": contamination}, "paper_only": True, "live_trading_enabled": False, "real_money_orders": 0})
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    daily = directory / "cash-generation-daily.json"
    daily.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")
    weekly = directory / "cash-generation-weekly.json"
    weekly.write_text(json.dumps({"week_ending": now.date().isoformat(), "verified_realized_weekly_pnl": base["realized_cash_pnl"], "daily_average": base["realized_cash_pnl"], "weekly_return": "REQUIRES_VERIFIED_CAPITAL", "capital_compounded": "FROM_COMPOUNDING_POLICY", "maximum_drawdown": "REQUIRES_EQUITY_CURVE", "profit_factor": base["profit_factor"], "expectancy": base["expectancy"], "trading_days": 1 if base["closed_trades"] else 0, "profitable_days": 1 if isinstance(base["realized_cash_pnl"], (int, float)) and base["realized_cash_pnl"] > 0 else 0, "losing_days": 1 if isinstance(base["realized_cash_pnl"], (int, float)) and base["realized_cash_pnl"] < 0 else 0, "capital_velocity": base["capital_velocity"], "income_target_progress": base["income_target_progress"], "paper_only": True}, indent=2, sort_keys=True) + "\n")
    return daily, weekly
