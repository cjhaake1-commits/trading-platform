"""Lawful public-research normalization with provenance and look-ahead safety."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

SOURCE_QUALITY = {
    "official": "OFFICIAL",
    "regulatory": "REGULATORY",
    "corporate": "PRIMARY_CORPORATE",
    "institutional": "INSTITUTIONAL_PUBLIC",
    "academic": "ACADEMIC",
    "major_news": "MAJOR_NEWS",
    "social": "SOCIAL",
    "community": "COMMUNITY",
}


@dataclass(frozen=True)
class PublicObservation:
    lane: str
    source: str
    provider: str
    endpoint: str
    instrument: str | None
    pillar: str
    source_quality: str
    observed_at: str | None
    retrieved_at: str
    freshness: str
    payload: dict[str, Any]
    observation_id: str

    def as_research_record(self) -> dict[str, object]:
        return {
            "research_id": self.observation_id,
            "lane": self.lane,
            "source": self.source,
            "source_url": self.endpoint,
            "source_type": self.source_quality,
            "as_of_date": self.observed_at,
            "retrieved_at": self.retrieved_at,
            "freshness": self.freshness,
            "instrument": self.instrument,
            "signal_type": "public_observation",
            "signal_value": None,
            "confidence": 0.0,
            "metadata_json": {"provider": self.provider, "pillar": self.pillar,
                              "source_quality": self.source_quality, "payload": self.payload},
            "paper_shadow_status": "RESEARCH_ONLY",
            "promotion_status": "COLLECTING_EVIDENCE",
            "model_weight": 0.0,
            "broker_control": 0,
        }


def normalize_public_observation(
    lane: str,
    payload: Mapping[str, Any],
    *,
    source: str,
    provider: str,
    endpoint: str,
    pillar: str,
    source_quality: str,
    instrument: str | None = None,
    observed_at: str | None = None,
    retrieved_at: datetime | None = None,
) -> PublicObservation:
    quality = SOURCE_QUALITY.get(source_quality.lower(), source_quality.upper())
    received = (retrieved_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    raw = f"{lane}|{source}|{provider}|{endpoint}|{instrument}|{observed_at}|{sorted(payload.items())}"
    observation_id = hashlib.sha256(raw.encode()).hexdigest()
    return PublicObservation(lane, source, provider, endpoint, instrument, pillar, quality,
                             observed_at, received, "FRESH" if observed_at else "INCOMPLETE",
                             dict(payload), observation_id)


def normalize_13f(record: Mapping[str, Any], *, endpoint: str, retrieved_at: datetime | None = None) -> PublicObservation:
    payload = {key: record.get(key) for key in (
        "institution", "filing_period", "filing_date", "security", "ticker", "cusip",
        "position_value", "position_change", "new_position", "closed_position", "weight",
    )}
    return normalize_public_observation("institutional", payload, source="sec_13f", provider="SEC",
                                        endpoint=endpoint, pillar="global", source_quality="regulatory",
                                        instrument=str(record.get("ticker") or record.get("cusip") or "") or None,
                                        observed_at=str(record.get("filing_date") or record.get("filing_period") or "") or None,
                                        retrieved_at=retrieved_at)


def normalize_etf(record: Mapping[str, Any], *, endpoint: str, retrieved_at: datetime | None = None) -> PublicObservation:
    return normalize_public_observation("etf_funds", dict(record), source="etf_holdings", provider=str(record.get("provider") or "unknown"),
                                        endpoint=endpoint, pillar=str(record.get("pillar") or "stocks"), source_quality="institutional",
                                        instrument=str(record.get("ticker") or "") or None, observed_at=str(record.get("as_of") or "") or None,
                                        retrieved_at=retrieved_at)


def normalize_news(record: Mapping[str, Any], *, endpoint: str, retrieved_at: datetime | None = None) -> PublicObservation:
    return normalize_public_observation("news", dict(record), source=str(record.get("source") or "unknown"), provider="public_news",
                                        endpoint=endpoint, pillar=str(record.get("pillar") or "global"), source_quality="major_news",
                                        instrument=str(record.get("symbol") or "") or None, observed_at=str(record.get("timestamp") or "") or None,
                                        retrieved_at=retrieved_at)
