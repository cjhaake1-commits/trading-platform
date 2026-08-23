"""Lawful public-data provider boundary with independent failure handling."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProviderResult:
    lane: str
    status: str
    records: list[dict[str, object]]
    error: str | None = None


def fetch_json_provider(lane: str, url: str, *, timeout: float = 10.0) -> ProviderResult:
    try:
        request = Request(url, headers={"User-Agent": "ChrisHaakeCapitalSystems/1.0 research-only"})
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("data") or payload.get("items") or (
                [payload] if any(key in payload for key in ("rates", "value", "observations")) else []
            )
        else:
            records = []
        if not isinstance(records, list):
            records = []
        return ProviderResult(lane, "CONNECTED", [item for item in records if isinstance(item, dict)])
    except Exception as exc:  # provider failures are isolated from trading
        return ProviderResult(lane, "UNAVAILABLE", [], type(exc).__name__ + ": " + str(exc)[:200])
