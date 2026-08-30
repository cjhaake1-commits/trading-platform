"""Durable forward-evidence bridge for research intelligence.

This module is deliberately broker-free.  It stores what was knowable at an
observation timestamp and creates idempotent jobs for later market outcomes.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

HORIZONS = {"30M": timedelta(minutes=30), "4H": timedelta(hours=4), "1D": timedelta(days=1),
            "5D": timedelta(days=5), "20D": timedelta(days=20)}


@dataclass(frozen=True)
class OutcomeJob:
    observation_id: str
    symbol: str
    horizon: str
    due_at: str
    decision: str = "RESEARCH_ONLY"


class IntelligenceLearningTree:
    def __init__(self, path: str | Path = "var/autotrader/research.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS intelligence_outcome_jobs (
                observation_id TEXT NOT NULL, symbol TEXT NOT NULL, horizon TEXT NOT NULL,
                due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
                return_pct REAL, benchmark_return_pct REAL, mfe REAL, mae REAL,
                volatility_change REAL, volume_change REAL, drawdown REAL,
                resolved_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(observation_id, horizon)
            );
            CREATE TABLE IF NOT EXISTS intelligence_hypotheses (
                hypothesis_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                status TEXT NOT NULL, sample_count INTEGER NOT NULL DEFAULT 0,
                forward_count INTEGER NOT NULL DEFAULT 0, expectancy REAL,
                max_drawdown REAL, reason TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intelligence_checkpoints (
                source TEXT PRIMARY KEY, last_attempt TEXT NOT NULL, last_success TEXT,
                records INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT
            );
            CREATE TABLE IF NOT EXISTS intelligence_attribution (
                hypothesis_id TEXT NOT NULL, feature_family TEXT NOT NULL, version TEXT NOT NULL,
                classification TEXT NOT NULL, sample_count INTEGER NOT NULL, expectancy_delta REAL,
                updated_at TEXT NOT NULL, PRIMARY KEY(hypothesis_id, feature_family, version)
            );
            CREATE INDEX IF NOT EXISTS idx_intelligence_jobs_due ON intelligence_outcome_jobs(status, due_at);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def schedule(self, *, observation_id: str, symbol: str, observed_at: str,
                 metadata: Mapping[str, Any] | None = None) -> int:
        base = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(UTC)
        rows = [(observation_id, symbol, horizon, (base + delta).isoformat(), json.dumps(dict(metadata or {}), sort_keys=True))
                for horizon, delta in HORIZONS.items()]
        with self._connect() as conn:
            conn.executemany("INSERT OR IGNORE INTO intelligence_outcome_jobs(observation_id,symbol,horizon,due_at,metadata_json) VALUES(?,?,?,?,?)", rows)
        return len(rows)

    def pending(self, *, now: datetime | None = None) -> list[dict[str, object]]:
        current = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM intelligence_outcome_jobs WHERE status='PENDING' AND due_at<=? ORDER BY due_at", (current,))]

    def resolve_from_public_store(self, public_db: str | Path = "var/autotrader/public-intelligence.db",
                                  *, now: datetime | None = None) -> dict[str, int]:
        """Resolve only jobs with a post-due public observation; missing data stays pending."""
        if not Path(public_db).exists():
            return {"resolved": 0, "pending": len(self.pending(now=now))}
        current = (now or datetime.now(UTC)).astimezone(UTC)
        public = sqlite3.connect(str(public_db), timeout=10.0)
        public.row_factory = sqlite3.Row
        try:
            jobs = self.pending(now=current)
            resolved = 0
            for job in jobs:
                row = public.execute("SELECT value,source_time FROM observations WHERE symbol=? AND value IS NOT NULL AND source_time IS NOT NULL ORDER BY source_time DESC LIMIT 1", (job["symbol"],)).fetchone()
                if row is None or str(row["source_time"]) < str(job["due_at"]):
                    continue
                meta = json.loads(str(job["metadata_json"] or "{}"))
                entry = meta.get("entry_price")
                if entry in (None, 0):
                    continue
                change = float(row["value"]) / float(entry) - 1.0
                if self.resolve(observation_id=str(job["observation_id"]), horizon=str(job["horizon"]), return_pct=change,
                                metadata={"observed_at": row["source_time"], "source": "public_intelligence"}):
                    resolved += 1
            return {"resolved": resolved, "pending": len(self.pending(now=current))}
        finally:
            public.close()

    def upsert_hypothesis(self, *, hypothesis_id: str, name: str, version: str,
                          sample_count: int, forward_count: int, expectancy: float | None,
                          max_drawdown: float | None, data_quality: str = "VALID") -> tuple[str, str]:
        status, reason = self.promotion_status(sample_count=sample_count, forward_count=forward_count,
                                                expectancy=expectancy, max_drawdown=max_drawdown,
                                                data_quality=data_quality)
        with self._connect() as conn:
            conn.execute("INSERT INTO intelligence_hypotheses(hypothesis_id,name,version,status,sample_count,forward_count,expectancy,max_drawdown,reason,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(hypothesis_id) DO UPDATE SET version=excluded.version,status=excluded.status,sample_count=excluded.sample_count,forward_count=excluded.forward_count,expectancy=excluded.expectancy,max_drawdown=excluded.max_drawdown,reason=excluded.reason,updated_at=excluded.updated_at",
                         (hypothesis_id, name, version, status, sample_count, forward_count, expectancy, max_drawdown, reason, datetime.now(UTC).isoformat()))
        return status, reason

    def register_observation_hypotheses(self, *, observation_id: str, symbol: str,
                                        signal_value: float = 0.0) -> int:
        """Create research groupings from observed evidence; never creates orders."""
        names = ("SOCIAL_ATTENTION_PLUS_VOLUME", "FILING_POSITIVE_DELTA_PLUS_MOMENTUM",
                 "FUNDAMENTAL_ACCELERATION", "CROSS_PILLAR_CONFIRMATION")
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.executemany("INSERT OR IGNORE INTO intelligence_hypotheses(hypothesis_id,name,version,status,reason,updated_at) VALUES(?,?,?,?,?,?)",
                             [(f"{name}:v1", name, "v1", "DISCOVERED", f"observation={observation_id}; signal={signal_value}", now) for name in names])
        return len(names)

    def record_attribution(self, *, hypothesis_id: str, feature_family: str, sample_count: int,
                           expectancy_delta: float | None, version: str = "v1") -> str:
        classification = "INSUFFICIENT_EVIDENCE" if sample_count < 30 else (
            "POSITIVE" if (expectancy_delta or 0) > 0 else "NEGATIVE" if (expectancy_delta or 0) < 0 else "NEUTRAL")
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO intelligence_attribution VALUES(?,?,?,?,?,?,?)",
                         (hypothesis_id, feature_family, version, classification, sample_count, expectancy_delta, datetime.now(UTC).isoformat()))
        return classification

    def resolve(self, *, observation_id: str, horizon: str, return_pct: float,
                mfe: float | None = None, mae: float | None = None,
                metadata: Mapping[str, Any] | None = None) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE intelligence_outcome_jobs SET status='RESOLVED',return_pct=?,mfe=?,mae=?,resolved_at=?,metadata_json=? WHERE observation_id=? AND horizon=? AND status='PENDING'",
                               (return_pct, mfe, mae, datetime.now(UTC).isoformat(), json.dumps(dict(metadata or {}), sort_keys=True), observation_id, horizon))
        return cur.rowcount == 1

    def checkpoint(self, source: str, *, status: str, records: int = 0, error: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("INSERT INTO intelligence_checkpoints(source,last_attempt,last_success,records,status,error) VALUES(?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt,last_success=CASE WHEN excluded.status='HEALTHY' THEN excluded.last_attempt ELSE intelligence_checkpoints.last_success END,records=excluded.records,status=excluded.status,error=excluded.error",
                         (source, now, now if status == "HEALTHY" else None, records, status, error))

    @staticmethod
    def promotion_status(*, sample_count: int, forward_count: int, expectancy: float | None,
                         max_drawdown: float | None, data_quality: str = "VALID") -> tuple[str, str]:
        if data_quality != "VALID":
            return "OBSERVING", "data quality incomplete"
        if sample_count < 100 or forward_count < 50:
            return "SHADOW_TESTING", "insufficient forward sample"
        if expectancy is None or expectancy <= 0:
            return "REJECTED", "non-positive forward expectancy"
        if max_drawdown is not None and max_drawdown > 0.15:
            return "REJECTED", "drawdown exceeds policy"
        return "ELIGIBLE_FOR_MODEL", "forward evidence and risk gates passed"
