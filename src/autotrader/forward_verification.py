"""Clean forward-verification epoch and append-only execution evidence."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Mapping
from zoneinfo import ZoneInfo

_LOCK = Lock()
EVENTS = {
    "INTENT_CREATED", "CAPITAL_RESERVED", "SUBMITTED", "ACKNOWLEDGED", "WORKING",
    "PARTIAL_FILL", "FILLED", "POSITION_OPENED", "EXIT_INTENT_CREATED", "EXIT_SUBMITTED",
    "EXIT_PARTIAL_FILL", "EXIT_FILLED", "POSITION_CLOSED", "SETTLED", "LIQUIDATED",
    "CANCELED", "REJECTED", "TIMEOUT", "UNKNOWN_PROVIDER_STATE", "RECONCILED", "CAPITAL_RELEASED",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_verification_epoch(path: str | Path = "var/autotrader/verification-epoch.json") -> dict[str, object]:
    destination = Path(path)
    if destination.exists():
        return json.loads(destination.read_text(encoding="utf-8"))
    started = _now()
    payload = {
        "schema_version": "forward-verification-epoch-v1",
        "experiment_id": "income_6000_v2",
        "verification_epoch_id": "VE-" + hashlib.sha256(started.encode()).hexdigest()[:16],
        "started_at": started,
        "capital_policy": "income_6000_v2:6x1000",
        "paper_only": True,
        "ownership_required": True,
        "cost_basis_required": True,
        "provider_fill_required": True,
        "realized_pnl_requires_exit_fill": True,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".verification-epoch-", dir=destination.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return payload


def deterministic_submission_id(*, experiment_id: str, epoch_id: str, pillar: str,
                                strategy: str, intent_id: str, max_length: int = 48) -> str:
    raw = "|".join((experiment_id, epoch_id, pillar, strategy, intent_id))
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    prefix = "ve-" + "-".join("".join(ch for ch in value.lower() if ch.isalnum())[:8]
                               for value in (pillar, strategy))
    return (prefix + "-" + digest)[:max_length]


def append_manifest(event_type: str, record: Mapping[str, object], *, path: str | Path = "var/autotrader/execution-manifest.jsonl") -> str:
    if event_type not in EVENTS:
        raise ValueError("unsupported forward lifecycle event")
    epoch = ensure_verification_epoch()
    event_id = str(record.get("event_id") or hashlib.sha256(
        json.dumps([event_type, dict(record)], sort_keys=True, default=str).encode()).hexdigest()
    )
    payload = {
        "event_id": event_id, "event_type": event_type, "timestamp": str(record.get("timestamp") or _now()),
        "timestamp_utc": str(record.get("timestamp_utc") or record.get("timestamp") or _now()),
        "experiment_id": record.get("experiment_id") or epoch["experiment_id"],
        "verification_epoch_id": record.get("verification_epoch_id") or epoch["verification_epoch_id"],
        "pillar": record.get("pillar", "UNKNOWN"), "strategy": record.get("strategy", "UNKNOWN"),
        "local_submission_id": record.get("local_submission_id", "UNKNOWN"),
        "provider": record.get("provider", "UNKNOWN"), "provider_environment": record.get("provider_environment", "UNKNOWN"),
        "provider_order_id": record.get("provider_order_id", "UNKNOWN"), "provider_fill_id": record.get("provider_fill_id", "UNKNOWN"),
        "symbol": record.get("symbol", record.get("ticker", "UNKNOWN")), "side": record.get("side", "UNKNOWN"),
        "quantity": record.get("quantity", "UNKNOWN"), "price": record.get("price", "UNKNOWN"),
        "capital_reserved": record.get("capital_reserved", "UNKNOWN"),
        "ownership_classification": record.get("ownership_classification", "OWNERSHIP_INCOMPLETE"),
        "order_intent_id": record.get("order_intent_id", record.get("intent_id", "UNKNOWN")),
        "requested_quantity": record.get("requested_quantity", "UNKNOWN"),
        "filled_quantity": record.get("filled_quantity", "UNKNOWN"),
        "remaining_quantity": record.get("remaining_quantity", "UNKNOWN"),
        "fill_price": record.get("fill_price", record.get("price", "UNKNOWN")),
        "fees": record.get("fees", "UNKNOWN"), "funding": record.get("funding", "UNKNOWN"),
        "reservation_id": record.get("reservation_id", "UNKNOWN"),
        "capital_released": record.get("capital_released", "UNKNOWN"),
        "ownership_confidence": record.get("ownership_confidence", "UNKNOWN"),
        "accounting_confidence": record.get("accounting_confidence", "UNKNOWN"),
        "source": record.get("source", "forward_verification"),
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True, default=str) + "\n"
    with _LOCK:
        if destination.exists():
            for existing in destination.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(existing).get("event_id") == event_id:
                        return event_id
                except ValueError:
                    continue
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    return event_id


def promote_provider_fill(*, record: Mapping[str, object], provider_order_id: str,
                          provider_fill_id: str, filled_quantity: object, fill_price: object,
                          fees: object = "UNKNOWN", funding: object = "UNKNOWN",
                          timestamp: str | None = None, path: str | Path = "var/autotrader/execution-manifest.jsonl") -> str:
    """Promote only a provider-linked fill; no ticker-only attribution."""
    local_id = str(record.get("local_submission_id") or "")
    if not local_id or not provider_order_id or not provider_fill_id:
        raise ValueError("provider fill requires local submission, order, and fill linkage")
    return append_manifest("FILLED", {
        **dict(record), "provider_order_id": provider_order_id, "provider_fill_id": provider_fill_id,
        "filled_quantity": filled_quantity, "quantity": filled_quantity, "fill_price": fill_price,
        "fees": fees, "funding": funding, "ownership_classification": "PLATFORM_OWNED_CURRENT_EXPERIMENT",
        "ownership_confidence": "HIGH", "accounting_confidence": "PARTIAL" if "UNKNOWN" in {str(fees), str(funding)} else "HIGH",
        "timestamp": timestamp or _now(), "path": path,
    }, path=path)


def forward_daily_metrics(*, manifest_path: str | Path = "var/autotrader/execution-manifest.jsonl",
                          output: str | Path = "var/reports/forward-verified-daily.json",
                          now: datetime | None = None,
                          report_date: str | None = None) -> dict[str, object]:
    epoch = ensure_verification_epoch()
    today = report_date or (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    events = []
    path = Path(manifest_path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if row.get("verification_epoch_id") == epoch["verification_epoch_id"]:
                    events.append(row)
            except ValueError:
                continue
    def local_day(row):
        try:
            value = datetime.fromisoformat(str(row.get("timestamp", "")).replace("Z", "+00:00"))
            return value.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        except ValueError:
            return None
    owned = [row for row in events if row.get("ownership_classification") == "PLATFORM_OWNED_CURRENT_EXPERIMENT"]
    closed = [row for row in owned if row.get("event_type") == "POSITION_CLOSED" and local_day(row) == today]
    fills = [row for row in owned if row.get("event_type") in {"FILLED", "EXIT_FILLED"} and local_day(row) == today
             and row.get("provider_order_id") not in {None, "UNKNOWN"}
             and row.get("provider_fill_id") not in {None, "UNKNOWN"}]
    open_count = sum(1 for row in owned if row.get("event_type") == "POSITION_OPENED") - sum(1 for row in owned if row.get("event_type") == "POSITION_CLOSED")
    realized_values = [row.get("realized_pnl") for row in closed]
    if not closed:
        realized = 0.0
    elif all(isinstance(value, (int, float)) for value in realized_values):
        realized = sum(realized_values)
    else:
        realized = "UNKNOWN"
    marks = [row.get("unrealized_pnl") for row in owned if row.get("event_type") in {"POSITION_OPENED", "RECONCILED"}]
    if open_count <= 0:
        unrealized = 0.0
    elif marks and all(isinstance(value, (int, float)) for value in marks):
        unrealized = sum(marks)
    else:
        unrealized = "UNKNOWN"
    payload = {
        "verification_epoch": epoch, "day": today, "timezone": "America/New_York",
        "fills_today": len(fills), "verified_closed_trades": len(closed),
        "verified_open_positions": max(open_count, 0),
        "realized_today": realized,
        "unrealized_now": unrealized, "capital_reserved": "FROM_RESERVATION_LEDGER", "capital_available": "FROM_RESERVATION_LEDGER",
        "unknown_provider_exposure": "PRESERVED_OUTSIDE_FORWARD_VERIFIED", "legacy_exposure": "PRESERVED_OUTSIDE_FORWARD_VERIFIED",
        "provider_observed_total": "SEE_PROVIDER_REPORT",
        "verification_confidence": "HIGH" if (fills or closed) else "NO_FORWARD_EXECUTION",
    }
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
