"""Bounded, restart-safe SEC polling/bootstrap coordinator."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .intelligence_learning import IntelligenceLearningTree
from .research_universe import ResearchUniverse


class SecResearchScheduler:
    def __init__(self, tree: IntelligenceLearningTree, *, universe: ResearchUniverse | None = None,
                 batch_size: int | None = None, user_agent: str | None = None) -> None:
        self.tree = tree
        self.universe = universe or ResearchUniverse.configured()
        self.batch_size = batch_size or int(os.getenv("SEC_BOOTSTRAP_BATCH_SIZE", "2"))
        self.user_agent = user_agent if user_agent is not None else (os.getenv("SEC_USER_AGENT") or os.getenv("PUBLIC_DATA_USER_AGENT"))

    def _checkpoint(self) -> dict[str, object]:
        with self.tree._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sec_filings(accession TEXT PRIMARY KEY,cik TEXT NOT NULL,form TEXT,filing_date TEXT,period_end TEXT,amended INTEGER NOT NULL DEFAULT 0,content_hash TEXT NOT NULL,retrieved_at TEXT NOT NULL,mode TEXT NOT NULL)")
            row = conn.execute("SELECT * FROM intelligence_checkpoints WHERE source='sec_bootstrap'").fetchone()
        return dict(row) if row else {"records": 0, "status": "NOT_STARTED"}

    def run_batch(self) -> dict[str, object]:
        started = datetime.now(UTC).isoformat()
        total = len(self.universe.securities)
        checkpoint = self._checkpoint()
        cursor = int(checkpoint.get("records") or 0)
        if not self.user_agent:
            self.tree.checkpoint("sec_bootstrap", status="AUTH_REQUIRED", records=cursor, error="SEC_USER_AGENT is not configured")
            return {"status": "AUTH_REQUIRED", "issuers_total": total, "issuers_completed": cursor, "issuers_remaining": max(0, total - cursor), "started_at": started}
        completed = cursor
        failed = 0
        filing_count = 0
        for security in self.universe.securities[cursor:cursor + self.batch_size]:
            try:
                cik = str(security.cik or "").zfill(10)
                request = Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": self.user_agent, "Accept": "application/json"})
                payload = None
                for attempt in range(3):
                    try:
                        with urlopen(request, timeout=12) as response:  # noqa: S310 - fixed SEC host
                            payload = json.load(response)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(min(8.0, 2.0 ** attempt))
                recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
                forms = recent.get("form", []) if isinstance(recent, dict) else []
                accessions = recent.get("accessionNumber", []) if isinstance(recent, dict) else []
                dates = recent.get("filingDate", []) if isinstance(recent, dict) else []
                periods = recent.get("reportDate", []) if isinstance(recent, dict) else []
                with self.tree._connect() as conn:
                    for index, accession in enumerate(accessions[:100]):
                        raw = json.dumps({"accession": accession, "form": forms[index] if index < len(forms) else None,
                                          "date": dates[index] if index < len(dates) else None}, sort_keys=True).encode()
                        conn.execute("INSERT OR IGNORE INTO sec_filings(accession,cik,form,filing_date,period_end,amended,content_hash,retrieved_at,mode) VALUES(?,?,?,?,?,?,?,?,?)",
                                     (str(accession), cik, forms[index] if index < len(forms) else None,
                                      dates[index] if index < len(dates) else None, periods[index] if index < len(periods) else None,
                                      int(str(forms[index] if index < len(forms) else '').endswith('/A')), hashlib.sha256(raw).hexdigest(),
                                      datetime.now(UTC).isoformat(), "HISTORICAL_BACKFILL" if cursor else "LIVE_FORWARD_OBSERVATION"))
                        filing_count += 1
                completed += 1
                time.sleep(float(os.getenv("SEC_MIN_INTERVAL_SECONDS", "0.2")))
            except Exception as exc:  # source failure is isolated
                failed += 1
                self.tree.checkpoint("sec_bootstrap", status="DEGRADED", records=completed, error=f"{type(exc).__name__}: {exc}")
        status = "HEALTHY" if completed >= total else "DEGRADED"
        self.tree.checkpoint("sec_bootstrap", status=status, records=completed, error=None if status == "HEALTHY" else f"batch completed; failed={failed}")
        self.tree.checkpoint("sec_live_poll", status=status, records=filing_count, error=None if status == "HEALTHY" else "poll degraded")
        return {"status": status, "issuers_total": total, "issuers_completed": completed,
                "issuers_remaining": max(0, total - completed), "failed": failed, "filings_ingested": filing_count, "started_at": started}
