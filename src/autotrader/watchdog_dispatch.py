"""Production watchdog dispatches for read-only reconciliation and learning."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .paper_experiment import PaperExperimentLedger

PROVIDERS = ("Alpaca", "OANDA", "Saxo", "Kalshi")


def dispatch_reconciliation(
    readers: dict[str, callable], *, validator=lambda value: value is not None
) -> list[dict[str, object]]:
    events = []
    for provider in PROVIDERS:
        reader = readers.get(provider)
        if reader is None:
            events.append({"provider": provider, "state": "UNKNOWN", "action": "NONE", "trading_side_effects": "NONE"})
            continue
        try:
            value = reader()
            if not validator(value):
                raise ValueError("invalid reconciliation result")
            events.append(
                {
                    "provider": provider,
                    "state": "RECOVERED",
                    "action": "READ_ONLY_RECONCILIATION",
                    "freshness": datetime.now(UTC).isoformat(),
                    "trading_side_effects": "NONE",
                }
            )
        except Exception as exc:
            events.append(
                {
                    "provider": provider,
                    "state": "RECONCILIATION_ERROR",
                    "error": type(exc).__name__,
                    "trading_side_effects": "NONE",
                }
            )
    return events


def dispatch_counterfactuals(
    *,
    ledger: PaperExperimentLedger | None = None,
    bars_by_symbol: dict[str, list[object]] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Settle only due observations through the existing provider-free path."""
    ledger = ledger or PaperExperimentLedger()
    now = now or datetime.now(UTC)
    bars_by_symbol = bars_by_symbol or {}
    counts = ledger.resolve_counterfactuals(bars_by_symbol, now=now)
    return {"state": "ACTIVE", "settlement": counts, "trading_side_effects": "NONE"}


def run_production_dispatch(
    *,
    readers: dict[str, callable] | None = None,
    ledger: PaperExperimentLedger | None = None,
    bars_by_symbol: dict[str, list[object]] | None = None,
    now: datetime | None = None,
    output: str = "var/reports/watchdog-dispatch.json",
) -> dict[str, object]:
    report = {
        "generated_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "reconciliation": dispatch_reconciliation(readers or {}),
        "counterfactual": dispatch_counterfactuals(ledger=ledger, bars_by_symbol=bars_by_symbol, now=now),
        "trading_side_effects": "NONE",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return report
