from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autotrader.brokers.alpaca_metals_paper import METALS_UNIVERSE
from autotrader.brokers.connectivity import test_alpaca_paper, test_oanda_practice
from autotrader.brokers.safety import alpaca_open_positions, oanda_open_positions
from autotrader.capital_allocations import TOTAL_PAPER_CAPITAL
from autotrader.cash_dashboard import aggregate_cash_dashboard
from autotrader.coordinated_test import FivePillarTestConfig, five_pillar_performance
from autotrader.experiment_state import ensure_experiment_state


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_backlog_checkpoint(path: Path = Path("var/autotrader/alpaca_backlog_checkpoint.json")) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_portfolio(
    path: Path,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
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
        try:
            crypto_states = [dict(row) for row in conn.execute("SELECT * FROM crypto_entry_state ORDER BY symbol")]
        except sqlite3.Error:
            crypto_states = []
        pillar_trades = []
        for table in ("international_trades", "metals_trades"):
            try:
                pillar_trades.extend(
                    dict(row)
                    for row in conn.execute(f"SELECT * FROM {table} WHERE status = 'closed' ORDER BY closed_at")
                )
            except sqlite3.Error:
                continue
    return ({} if state is None else dict(state), positions, fills, pillar_trades, crypto_states)


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


def read_learning(learning_dir: Path = Path("var/autotrader/learning")) -> dict[str, object]:
    stats = read_json(learning_dir / "performance_stats.json")
    parameters = read_json(learning_dir / "learned_parameters.json")
    model_state = read_json(learning_dir / "model_state.json")
    history_path = learning_dir / "learning_history.jsonl"
    history: list[dict[str, object]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                history.append(item)
    return {
        "stats": stats,
        "parameters": parameters,
        "model_state": model_state,
        "history": history[-20:],
    }


def ledger_stop_map(rows: list[dict[str, object]]) -> dict[str, float]:
    return {str(row.get("symbol") or ""): _float(row.get("stop_price")) for row in rows}


def _canonical_crypto_symbol(symbol: object) -> str:
    raw = str(symbol or "").replace("_", "/").upper()
    if "/" in raw:
        return raw
    for quote in ("USD", "USDT", "USDC"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[:-len(quote)]}/{quote}"
    return raw


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        return observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _classify_position_for_experiment(
    row: dict[str, object],
    *,
    experiment_start: datetime | None,
) -> tuple[str, bool, str]:
    metadata = row.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if isinstance(metadata, dict):
        experiment_id = str(metadata.get("experiment_id") or "").strip()
        if experiment_id == "five_pillar_paper_v2" or metadata.get("learning_eligible") is True:
            return "VALID_STRATEGY_POSITION", True, "durable v2 experiment provenance"
    opened_at = _parse_iso(row.get("opened_at"))
    if experiment_start is not None and opened_at is not None and opened_at < experiment_start:
        return "LEGACY", False, "opened before experiment baseline"
    return "UNKNOWN", False, "durable experiment provenance is missing"


def _serialize_position(
    row: dict[str, object],
    *,
    experiment_start: datetime | None,
    source: str,
) -> dict[str, object]:
    classification, learning_eligible, classification_reason = _classify_position_for_experiment(
        row,
        experiment_start=experiment_start,
    )
    output = dict(row)
    output.update(
        {
            "source": source,
            "classification": classification,
            "classification_reason": classification_reason,
            "learning_eligible": learning_eligible,
            "learning_eligible_reason": (
                "eligible controlled-experiment evidence" if learning_eligible else classification_reason
            ),
        }
    )
    return output


def _aggregate_experiment_records(
    rows: list[dict[str, object]],
    *,
    experiment_start: datetime | None,
) -> list[dict[str, object]]:
    eligible: list[dict[str, object]] = []
    for row in rows:
        occurred_at = _parse_iso(row.get("occurred_at") or row.get("closed_at") or row.get("opened_at"))
        if experiment_start is not None and occurred_at is not None and occurred_at < experiment_start:
            continue
        metadata = row.get("metadata_json")
        learning_eligible = False
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if isinstance(metadata, dict):
            learning_eligible = bool(metadata.get("learning_eligible"))
        if learning_eligible:
            eligible.append(row)
    return eligible


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
        raw_alpaca = None
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
        raw_oanda = None
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

    if not positions and ledger_rows:
        for row in ledger_rows:
            symbol = str(row.get("symbol") or "")
            asset_class = str(row.get("asset_class") or "").lower()
            broker = str(row.get("broker") or "Ledger Snapshot") or "Ledger Snapshot"
            if asset_class == "forex" or "/" in symbol:
                pillar = "Forex"
            elif symbol.upper() in METALS_UNIVERSE:
                pillar = "Metals/Commodities"
            else:
                pillar = "Stocks/Crypto"
            qty = _float(row.get("quantity"))
            avg = _float(row.get("average_price"))
            market_value = abs(qty * avg)
            positions.append(
                {
                    "pillar": pillar,
                    "broker": broker,
                    "symbol": symbol,
                    "asset_class": asset_class or "snapshot",
                    "quantity": qty,
                    "average_price": avg,
                    "current_price": avg,
                    "stop_price": _float(row.get("stop_price")) or None,
                    "market_value": market_value,
                    "unrealized_pnl": _float(row.get("realized_pnl")),
                    "unrealized_pct": None,
                    "risk_dollars": 0.0,
                    "source": "ledger_snapshot",
                }
            )
            metrics["unrealized_pnl"] += _float(row.get("realized_pnl"))
            metrics["gross_exposure"] += market_value
            if asset_class == "forex" or "/" in symbol:
                metrics["oanda_exposure"] += market_value
            else:
                metrics["alpaca_exposure"] += market_value
    elif ledger_rows and not any(str(row.get("pillar") or "").startswith("Forex") for row in positions):
        for row in ledger_rows:
            if str(row.get("asset_class") or "").lower() != "forex":
                continue
            symbol = str(row.get("symbol") or "").replace("_", "/")
            qty = _float(row.get("quantity"))
            avg = _float(row.get("average_price"))
            exposure = abs(qty * avg)
            positions.append(
                {
                    "pillar": "Forex",
                    "broker": str(row.get("broker") or "Ledger Snapshot") or "Ledger Snapshot",
                    "symbol": symbol,
                    "asset_class": "forex",
                    "quantity": qty,
                    "average_price": avg,
                    "current_price": avg,
                    "stop_price": _float(row.get("stop_price")) or None,
                    "market_value": exposure,
                    "unrealized_pnl": _float(row.get("realized_pnl")),
                    "unrealized_pct": None,
                    "risk_dollars": 0.0,
                    "source": "ledger_snapshot",
                }
            )
            metrics["unrealized_pnl"] += _float(row.get("realized_pnl"))
            metrics["gross_exposure"] += exposure
            metrics["oanda_exposure"] += exposure

    return positions, metrics


def build_snapshot(status_path: Path, ledger_path: Path, audit_path: Path) -> dict[str, object]:
    status = read_json(status_path)
    experiment_state = ensure_experiment_state()
    experiment_start = _parse_iso(experiment_state.get("baseline_start_time"))
    portfolio_data = read_portfolio(ledger_path)
    if len(portfolio_data) == 4:
        state, ledger_positions, fills, pillar_trades = portfolio_data
        crypto_states = []
    else:
        state, ledger_positions, fills, pillar_trades, crypto_states = portfolio_data
    activity, latest_cycle = read_activity(audit_path)
    learning = read_learning()
    alpaca_connection = test_alpaca_paper()
    oanda_connection = test_oanda_practice()
    live_positions, broker_metrics = live_broker_positions(ledger_positions)
    crypto_by_symbol = {_canonical_crypto_symbol(row.get("symbol")): row for row in crypto_states}
    unresolved_manifests: list[dict[str, object]] = []
    if ledger_path.exists():
        with sqlite3.connect(ledger_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT manifest_id, canonical_symbol, broker_order_id, lifecycle_state, created_at
                    FROM entry_manifests
                    WHERE lifecycle_state IN (
                        'approved_manifest',
                        'order_submitted',
                        'order_pending',
                        'filled_position_pending',
                        'reconciliation_pending',
                        'protection_pending'
                    )
                    ORDER BY created_at, manifest_id
                    """
                ).fetchall()
            except sqlite3.Error:
                rows = []
            unresolved_manifests = [dict(row) for row in rows]
    backlog_checkpoint = read_backlog_checkpoint()
    ledger_position_index = {
        str(row.get("symbol") or "").replace("_", "/").upper(): dict(row)
        for row in ledger_positions
        if isinstance(row, dict)
    }
    active_experiment_unresolved = 0
    legacy_backlog_total = 0
    legacy_backlog_deferred = 0
    legacy_backlog_manual_review = 0
    if unresolved_manifests:
        for row in unresolved_manifests:
            created_at = _parse_iso(row.get("created_at"))
            experiment_match = False
            metadata = row.get("metadata_json")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            if isinstance(metadata, dict):
                experiment_match = (
                    str(metadata.get("experiment_id") or "").strip()
                    == experiment_state.get("experiment_id")
                )
            if experiment_match or (
                created_at is not None
                and experiment_start is not None
                and created_at >= experiment_start
            ):
                active_experiment_unresolved += 1
            else:
                legacy_backlog_total += 1
                legacy_backlog_deferred += 1

    classified_positions = []
    for row in live_positions:
        merged_row = dict(row)
        ledger_row = ledger_position_index.get(str(row.get("symbol") or "").replace("_", "/").upper())
        if ledger_row:
            for key in ("opened_at", "broker", "broker_position_id"):
                if merged_row.get(key) in {None, ""} and ledger_row.get(key) not in {None, ""}:
                    merged_row[key] = ledger_row.get(key)
        classified_positions.append(
            _serialize_position(merged_row, experiment_start=experiment_start, source="broker")
        )
    for position in classified_positions:
        if str(position.get("broker")) == "Alpaca Paper" and str(position.get("symbol") or "").upper().endswith("USD"):
            crypto = crypto_by_symbol.get(_canonical_crypto_symbol(position.get("symbol")), {})
            if isinstance(crypto, dict):
                position.update(
                    {
                        "crypto_lifecycle_state": crypto.get("lifecycle_state"),
                        "crypto_reconciliation_status": crypto.get("reconciliation_status"),
                        "crypto_reconciliation_difference": crypto.get("reconciliation_difference"),
                        "crypto_reconciliation_tolerance": crypto.get("reconciliation_tolerance"),
                        "crypto_protection_state": crypto.get("protection_state"),
                        "crypto_protection_quantity": crypto.get("protection_quantity"),
                        "crypto_stop_price": crypto.get("stop_price"),
                    }
                )
    active_positions = [row for row in classified_positions if row.get("learning_eligible")]
    legacy_positions = [row for row in classified_positions if not row.get("learning_eligible")]
    active_records = _aggregate_experiment_records([*fills, *pillar_trades], experiment_start=experiment_start)
    active_deployed = sum(_float(row.get("market_value")) for row in active_positions)
    active_realized_cash = sum(
        _float(record.get("realized_pnl")) - _float(record.get("fees_costs"))
        for record in active_records
    )

    jobs = status.get("jobs") if isinstance(status.get("jobs"), dict) else {}
    auto = jobs.get("autonomous-paper-trading") if isinstance(jobs, dict) else {}
    if not isinstance(auto, dict):
        auto = {}

    base_equity = TOTAL_PAPER_CAPITAL
    peak = max(_float(state.get("peak_equity"), base_equity), base_equity)
    broker_open_pnl = broker_metrics["unrealized_pnl"]
    broker_marked_equity = base_equity + broker_open_pnl
    drawdown = max((peak - broker_marked_equity) / peak, 0.0) if peak > 0 else 0.0
    gross_exposure = broker_metrics["gross_exposure"]
    risk_open = sum(_float(row.get("risk_dollars")) for row in classified_positions)
    last_heartbeat = status.get("last_heartbeat_at")
    heartbeat_current = _heartbeat_is_current(last_heartbeat)
    health_job = jobs.get("health") if isinstance(jobs, dict) else {}
    if not isinstance(health_job, dict):
        health_job = {}
    reported_healthy = status.get("healthy")
    if isinstance(reported_healthy, bool):
        healthy = reported_healthy and heartbeat_current
    else:
        healthy = (
            heartbeat_current
            and not bool(health_job.get("disabled"))
            and not bool(health_job.get("consecutive_failures"))
            and not bool(health_job.get("last_error"))
        )
    autonomous_enabled = status.get("autonomous_enabled") is True
    execution_state = "faulted" if not healthy else ("armed_paper" if autonomous_enabled else "disarmed")

    stretch_low = 0.20
    stretch_high = 0.40
    mtm_return = (broker_marked_equity - base_equity) / base_equity if base_equity > 0 else 0.0
    active_cash_dashboard = aggregate_cash_dashboard(
        realized_records=active_records,
        positions=active_positions,
        available_cash=max(TOTAL_PAPER_CAPITAL + active_realized_cash - active_deployed, 0.0),
        original_capital=TOTAL_PAPER_CAPITAL,
        broker_reported_virtual_equity=_float((alpaca_connection.details or {}).get("equity"))
        if alpaca_connection.ok
        else None,
    )
    broker_history_cash_dashboard = aggregate_cash_dashboard(
        realized_records=[*fills, *pillar_trades],
        positions=classified_positions,
        available_cash=max(
            (
                (_float((alpaca_connection.details or {}).get("cash")) if alpaca_connection.ok else 0.0)
                + (_float((oanda_connection.details or {}).get("balance")) if oanda_connection.ok else 0.0)
                - gross_exposure
            ),
            0.0,
        ),
        original_capital=TOTAL_PAPER_CAPITAL,
        broker_reported_virtual_equity=(
            _float((alpaca_connection.details or {}).get("equity")) if alpaca_connection.ok else None
        ),
    )
    pillar_performance = five_pillar_performance(
        completed_trades=active_records,
        positions=active_positions,
    )
    return {
        "published_at": datetime.now(UTC).isoformat(),
        "experiment": {
            "experiment_id": experiment_state.get("experiment_id", "five_pillar_paper_v2"),
            "baseline_start_time": experiment_state.get("baseline_start_time"),
            "created_at": experiment_state.get("created_at"),
            "capital_baseline": TOTAL_PAPER_CAPITAL,
            "pillar_cap": 1000.0,
        },
        "runtime": {
            "mode": status.get("mode", "paper"),
            "healthy": healthy,
            "autonomous_enabled": autonomous_enabled,
            "execution_state": execution_state,
            "live_trading_enabled": False,
            "last_heartbeat_at": last_heartbeat,
            # Missing/unreadable runtime state must display as disarmed, never enabled.
            "autonomous_job_disabled": bool(auto.get("disabled", True)),
            "consecutive_failures": int(auto.get("consecutive_failures", 0) or 0),
            "last_error": auto.get("last_error") if execution_state == "faulted" else None,
            "execution_message": auto.get("last_error"),
            "last_cycle_started_at": auto.get("last_started_at"),
            "last_cycle_finished_at": auto.get("last_finished_at"),
            "last_cycle_duration_ms": auto.get("last_duration_ms"),
            "unresolved_manifest_count": len(unresolved_manifests),
            "rate_limit_telemetry": {
                "requests": int((latest_cycle.get("broker_requests") or 0) or 0),
                "retries": int((latest_cycle.get("broker_retries") or 0) or 0),
                "rate_limited": int((latest_cycle.get("broker_rate_limited") or 0) or 0),
                "deferred": int((latest_cycle.get("broker_deferred") or 0) or 0),
            },
            "backlog_progress": {
                "legacy_total": legacy_backlog_total,
                "legacy_resolved": 0,
                "legacy_deferred": legacy_backlog_deferred,
                "legacy_manual_review": legacy_backlog_manual_review,
                "active_experiment_unresolved": active_experiment_unresolved,
                "percent_complete": 0.0 if legacy_backlog_total == 0 else 0.0,
                "oldest_unresolved_timestamp": unresolved_manifests[0]["created_at"] if unresolved_manifests else None,
                "newest_unresolved_timestamp": unresolved_manifests[-1]["created_at"] if unresolved_manifests else None,
                "current_history_window": {
                    "start": backlog_checkpoint.get("history_window_start"),
                    "end": backlog_checkpoint.get("history_window_end"),
                },
                "cooldown_until": backlog_checkpoint.get("retry_after_until"),
                "last_successful_reconciliation": backlog_checkpoint.get("last_successful_request"),
            },
        },
            "portfolio": {
                "base_equity": base_equity,
                "marked_equity": broker_marked_equity,
                "open_unrealized_pnl": broker_open_pnl,
            "mtm_return_pct": mtm_return,
            "drawdown_pct": drawdown,
            "gross_exposure": gross_exposure,
            "open_risk_dollars": risk_open,
            "alpaca_exposure": broker_metrics["alpaca_exposure"],
            "metals_exposure": broker_metrics["metals_exposure"],
            "oanda_exposure": broker_metrics["oanda_exposure"],
        },
        "broker_account": {
            "alpaca": alpaca_connection.details if alpaca_connection.ok else {},
            "oanda": oanda_connection.details if oanda_connection.ok else {},
            "equity_proxy": broker_marked_equity,
            "cash_proxy": max(
                (
                    (_float((alpaca_connection.details or {}).get("cash")) if alpaca_connection.ok else 0.0)
                    + (_float((oanda_connection.details or {}).get("balance")) if oanda_connection.ok else 0.0)
                    - gross_exposure
                ),
                0.0,
            ),
            "gross_exposure": gross_exposure,
            "unrealized_pnl": broker_open_pnl,
            "history_note": "Broker paper account history; not the active strategy experiment.",
        },
        "targets": {
            "stretch_daily_low_pct": stretch_low,
            "stretch_daily_high_pct": stretch_high,
            "progress_to_low": mtm_return / stretch_low if stretch_low else 0.0,
            "progress_to_high": mtm_return / stretch_high if stretch_high else 0.0,
            "note": (
                "Stretch benchmark only; the trader does not force trades to hit it. "
                "20%-40% DAILY RETURN is reporting only."
            ),
        },
        "guardrails": {
            "risk_per_trade_pct": 0.0125,
            "max_daily_loss_pct": 0.05,
            "max_peak_drawdown_pct": 0.15,
        },
        "cash_dashboard": active_cash_dashboard.as_dict(),
        "legacy_cash_dashboard": broker_history_cash_dashboard.as_dict(),
        "coordinated_test": FivePillarTestConfig().as_dict(),
        "pillar_performance": pillar_performance,
        "learning": learning,
        "fill_count": len(fills),
        "positions": classified_positions,
        "broker_positions": classified_positions,
        "active_positions": active_positions,
        "legacy_positions": legacy_positions,
        "latest_cycle": latest_cycle,
        "activity": activity,
        "unresolved_manifests": unresolved_manifests,
    }


def _heartbeat_is_current(value: object, *, now: datetime | None = None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        return False
    current = now or datetime.now(UTC)
    age = current - observed.astimezone(UTC)
    return timedelta(seconds=-5) <= age <= timedelta(seconds=90)


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
