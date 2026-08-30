#!/usr/bin/env python3
"""Fail closed unless runtime/provider evidence remains paper or demo only."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _read(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def verify(paths: tuple[str, ...] = ("var/autotrader/status.json", "var/kalshi/execution-predictions.json", "var/kalshi/execution-perps.json")) -> dict[str, object]:
    violations: list[str] = []
    checked: list[str] = []
    for name in ("LIVE_TRADING_ENABLED", "KALSHI_LIVE_TRADING_ENABLED"):
        if os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}:
            violations.append(f"live_environment_variable:{name}")
    if os.getenv("ALPACA_ENV", "paper").strip().lower() in {"live", "production"}:
        violations.append("live_environment_variable:ALPACA_ENV")
    for raw_path in paths:
        path = Path(raw_path)
        payload = _read(path)
        checked.append(raw_path)
        if not payload:
            violations.append(f"missing_or_invalid:{raw_path}")
            continue
        if payload.get("live_trading_enabled") is True or payload.get("live_mode") is True:
            violations.append(f"live_mode:{raw_path}")
        if payload.get("real_money_orders", 0) not in (0, "0", None):
            violations.append(f"real_money_orders:{raw_path}")
        if payload.get("environment") in {"live", "production"}:
            violations.append(f"live_environment:{raw_path}")
    return {"safe": not violations, "violations": violations, "checked": checked, "policy": "paper/simulation/demo only; fail closed on unknown or live evidence"}


def main() -> None:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    if not result["safe"]:
        raise SystemExit(20)


if __name__ == "__main__":
    main()
