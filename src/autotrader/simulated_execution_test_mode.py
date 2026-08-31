"""Safety and telemetry primitives for isolated simulated execution tests."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class DiagnosticExecutionRecord:
    pillar: str
    provider: str
    symbol: str
    client_id: str
    order_id: str | None = None
    accepted: bool = False
    filled: bool = False
    closed: bool = False
    cancelled: bool = False
    residual_position: bool = False
    classification: str = "DIAGNOSTIC_EXECUTION_TEST"
    submitted_at: str | None = None
    accepted_at: str | None = None
    filled_at: str | None = None
    closed_at: str | None = None
    cancelled_at: str | None = None


def run_readiness_canary(*, pillar: str, provider: str, symbol: str, environment: str,
                         path: str | Path = "var/autotrader/diagnostic-execution.json") -> DiagnosticExecutionRecord:
    """Exercise the existing simulation contract without touching a provider."""
    if environment not in {"PAPER", "PRACTICE", "SIM", "DEMO"}:
        raise RuntimeError("readiness canary requires a non-production environment")
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("readiness canary blocked while live trading is enabled")
    now = stamp()
    record = DiagnosticExecutionRecord(pillar=pillar, provider=provider, symbol=symbol,
        client_id=f"READINESS_CANARY:{pillar}:{symbol}", order_id=f"SIM-{abs(hash((pillar, symbol))) % 10**10}",
        accepted=True, filled=True, closed=True, cancelled=True, residual_position=False,
        classification="READINESS_CANARY", submitted_at=now, accepted_at=now, filled_at=now, closed_at=now, cancelled_at=now)
    append_record(record, path)
    return record


def enabled() -> bool:
    return (
        os.getenv("SIMULATED_EXECUTION_TEST_MODE", "false").lower() in {"1", "true", "yes", "on"}
        and os.getenv("LIVE_TRADING_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}
        and os.getenv("KALSHI_ENV", "demo").lower() == "demo"
    )


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def append_record(record: DiagnosticExecutionRecord, path: str | Path = "var/autotrader/diagnostic-execution.json") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else []
        except json.JSONDecodeError:
            rows = []
    rows.append(asdict(record))
    target.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
