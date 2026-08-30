"""Bounded, restart-safe SEC polling/bootstrap coordinator."""
from __future__ import annotations

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
        for security in self.universe.securities[cursor:cursor + self.batch_size]:
            try:
                cik = str(security.cik or "").zfill(10)
                request = Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": self.user_agent, "Accept": "application/json"})
                with urlopen(request, timeout=12) as response:  # noqa: S310 - fixed SEC host
                    json.load(response)
                completed += 1
                time.sleep(float(os.getenv("SEC_MIN_INTERVAL_SECONDS", "0.2")))
            except Exception as exc:  # source failure is isolated
                failed += 1
                self.tree.checkpoint("sec_bootstrap", status="DEGRADED", records=completed, error=f"{type(exc).__name__}: {exc}")
        status = "HEALTHY" if completed >= total else "DEGRADED"
        self.tree.checkpoint("sec_bootstrap", status=status, records=completed, error=None if status == "HEALTHY" else f"batch completed; failed={failed}")
        return {"status": status, "issuers_total": total, "issuers_completed": completed,
                "issuers_remaining": max(0, total - completed), "failed": failed, "started_at": started}
