#!/usr/bin/env python3
"""Bounded, read-only Kalshi Demo connectivity probe."""
from __future__ import annotations

import argparse
import json

from autotrader.kalshi.client import KalshiReadOnlyClient
from autotrader.kalshi.config import KalshiConfig


def probe(family: str) -> dict:
    config = KalshiConfig.from_env()
    result = {"environment": config.environment, "endpoint_family": family, "authentication": "CONNECTED" if config.api_key_id and config.private_key_path else "CREDENTIALS_NOT_CONFIGURED"}
    if result["authentication"] == "CREDENTIALS_NOT_CONFIGURED":
        return result
    client = KalshiReadOnlyClient(config)
    try:
        if family == "status":
            data = client.exchange_status()
        elif family == "predictions":
            data = client.events(limit="1")
        else:
            data = client.perps_enabled()
        result.update(http_state="OK", records_returned=len(data.get("events", data.get("markets", []))) if isinstance(data, dict) else 0, telemetry=client.telemetry.__dict__)
    except RuntimeError as exc:
        result.update(http_state="BLOCKED", last_error=type(exc).__name__)
    except Exception as exc:
        result.update(http_state="ERROR", last_error=type(exc).__name__)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("family", choices=("status", "predictions", "perps", "all"), default="status", nargs="?")
    args = parser.parse_args()
    values = {f: probe(f) for f in (("status", "predictions", "perps") if args.family == "all" else (args.family,))}
    print(json.dumps(values, sort_keys=True, default=str))
