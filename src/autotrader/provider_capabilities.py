"""Explicit capability records; unsupported and unknown remain distinct."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Capability:
    provider: str
    environment: str
    capability: str
    state: str
    reason: str


def capability_matrix(
    records: list[Capability], path: str | Path = "var/autotrader/provider-capabilities.json"
) -> list[dict[str, str]]:
    if any(item.state not in {"SUPPORTED", "UNSUPPORTED", "UNKNOWN", "BLOCKED"} for item in records):
        raise ValueError("invalid capability state")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(item) for item in records]
    output.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return data
