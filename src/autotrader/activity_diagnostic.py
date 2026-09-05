"""Durable backend activity and idle-capital diagnostics."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path
from typing import Mapping
from .margin_runtime import calculate_margin


def persist_activity(data: Mapping[str, object], *, path: str | Path = "var/autotrader/activity-diagnostic.jsonl", now: datetime | None = None) -> dict[str, object]:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    reasons = Counter()
    for key in ("rejection", "reason", "final_bottleneck", "last_rejection_reason"):
        value = data.get(key)
        if value:
            reasons[str(value)] += 1
    deployed = float(data.get("capital_deployed", data.get("deployed_capital", 0)) or 0)
    available = float(data.get("capital_available", data.get("available_capital", 0)) or 0)
    idle_reason = str(data.get("why_is_capital_idle") or next(iter(reasons), "NO_QUALIFIED_EDGE" if available > 0 else "NONE"))
    record = {"timestamp": (now or datetime.now(UTC)).isoformat(),
              "economic_capital": data.get("economic_capital"), "economic_equity": data.get("economic_equity"),
              "deployed_capital": deployed, "available_capital": available,
              "utilization": deployed / (deployed + available) if deployed + available > 0 else 0.0,
              "qualified_opportunities": int(data.get("qualified_opportunities", data.get("qualified", 0)) or 0),
              "rejected_opportunities": int(data.get("rejected_opportunities", data.get("rejected", 0)) or 0),
              "working_orders": int(data.get("working_orders", data.get("orders", 0)) or 0),
              "platform_owned_positions": int(data.get("platform_owned_positions", data.get("positions", 0)) or 0),
              "capital_released": float(data.get("capital_released", 0) or 0),
              "capital_redeployed": float(data.get("capital_redeployed", 0) or 0),
              "why_is_capital_idle": idle_reason, "idle_capital_by_reason": dict(reasons)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return record


def margin_snapshot(data: Mapping[str, object]) -> dict[str, object]:
    """Derive margin from economic notional, never provider buying power."""
    state = calculate_margin(
        economic_equity=float(data.get("economic_equity", data.get("equity", 0)) or 0),
        long_notional=float(data.get("long_notional", 0) or 0),
        short_notional=float(data.get("short_notional", 0) or 0),
        margin_used=float(data.get("margin_used", 0) or 0),
        platform_limit=float(data["platform_margin_limit"]) if data.get("platform_margin_limit") is not None else None,
        enabled=bool(data.get("margin_supported", False)),
    )
    return state.as_dict()
