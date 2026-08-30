"""SEC EDGAR normalization primitives; transport is injected for deterministic tests."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class Filing:
    accession: str
    cik: str
    form: str
    filed_at: str
    period_end: str | None
    amended: bool
    content_hash: str
    facts: Mapping[str, Any]
    source: str = "SEC_EDGAR"

    def record(self, *, retrieved_at: str | None = None) -> dict[str, object]:
        retrieved = retrieved_at or datetime.now(UTC).isoformat()
        return {"research_id": f"sec:{self.accession}:{self.content_hash[:16]}", "lane": "corporate",
                "source": self.source, "source_url": "https://www.sec.gov/edgar", "source_type": "REGULATORY",
                "as_of_date": self.filed_at, "retrieved_at": retrieved, "freshness": "FRESH",
                "instrument": self.cik, "signal_type": "SEC_FILING", "signal_value": None, "confidence": 1.0,
                "metadata_json": {"accession": self.accession, "cik": self.cik, "form": self.form,
                                  "period_end": self.period_end, "amended": self.amended,
                                  "content_hash": self.content_hash, "facts": dict(self.facts),
                                  "effective_at": self.filed_at, "point_in_time": True,
                                  "authorization": "PUBLIC_REGULATORY"},
                "paper_shadow_status": "RESEARCH_ONLY", "promotion_status": "OBSERVING",
                "model_weight": 0.0, "broker_control": 0}


def normalize_filing(payload: Mapping[str, Any], *, raw: bytes | str = b"") -> Filing:
    accession = str(payload.get("accession") or payload.get("accessionNumber") or "").replace("-", "")
    if not accession:
        raise ValueError("SEC filing requires accession")
    form = str(payload.get("form") or "").upper()
    filed = str(payload.get("filed") or payload.get("filing_date") or "")
    if not filed:
        raise ValueError("SEC filing requires filed date")
    raw_bytes = raw.encode() if isinstance(raw, str) else raw
    digest = hashlib.sha256(raw_bytes or json.dumps(dict(payload), sort_keys=True, default=str).encode()).hexdigest()
    return Filing(accession, str(payload.get("cik") or payload.get("cik_str") or ""), form, filed,
                  str(payload.get("period") or payload.get("period_end") or "") or None,
                  form.endswith("/A") or bool(payload.get("amended")), digest,
                  payload.get("facts") if isinstance(payload.get("facts"), Mapping) else {})
