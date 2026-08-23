#!/usr/bin/env python3
"""Independent, configured-public-source research cycle; never submits orders."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path

from autotrader.public_research import normalize_public_observation
from autotrader.research_platform import ResearchStore
from autotrader.research_providers import fetch_json_provider

LANES = ("institutional", "13f", "etf_funds", "macro", "news", "social", "political", "academic", "github")


def cycle() -> dict[str, object]:
    store = ResearchStore(os.getenv("GLOBAL_RESEARCH_DB", "var/autotrader/research.db"))
    results: dict[str, object] = {"retrieved_at": datetime.now(UTC).isoformat(), "lanes": {}}
    for lane in LANES:
        url = os.getenv(f"PUBLIC_RESEARCH_{lane.upper()}_URL")
        if not url:
            store.put_provider_status(lane, status="UNAVAILABLE", records_ingested=0, last_error="No permitted endpoint configured")
            results["lanes"][lane] = {"status": "UNAVAILABLE", "records": 0}
            continue
        fetched = fetch_json_provider(lane, url)
        saved = 0
        if fetched.status == "CONNECTED":
            for payload in fetched.records:
                observation = normalize_public_observation(lane, payload, source=lane, provider=lane,
                    endpoint=url, pillar=str(payload.get("pillar") or "global"), source_quality=str(payload.get("source_quality") or "unknown"),
                    instrument=str(payload.get("ticker") or payload.get("symbol") or "") or None,
                    observed_at=str(payload.get("timestamp") or payload.get("as_of") or "") or None)
                store.put_research(observation.as_research_record())
                for key, value in payload.items():
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        continue
                    if isfinite(numeric):
                        store.put_feature(name=f"{lane}.{key}", value=numeric, source=observation.source,
                                          experiment_id="global_research", symbol=observation.instrument or "global",
                                          pillar=observation.pillar, freshness=observation.freshness)
                saved += 1
        store.put_provider_status(lane, status=fetched.status, records_ingested=saved, last_error=fetched.error)
        results["lanes"][lane] = {"status": fetched.status, "records": saved, "error": fetched.error}
    path = Path(os.getenv("GLOBAL_RESEARCH_STATUS", "var/global-intelligence/public-research.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, sort_keys=True) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    print(json.dumps(cycle(), sort_keys=True))
