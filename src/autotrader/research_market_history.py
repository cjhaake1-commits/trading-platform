"""Research-only market history storage. No broker or order interfaces."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


class ResearchMarketHistory:
    def __init__(self, path: str | Path = "var/autotrader/public-intelligence.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS market_bars (pillar TEXT, provider TEXT, symbol TEXT, source_time TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, market_session TEXT, observed_at TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(provider,symbol,source_time))")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_bars_lookup ON market_bars(symbol,source_time)")

    def append(self, bars: Iterable[Mapping[str, Any]], *, provider: str, source: str, pillar: str = "UNKNOWN", observed_at: str | None = None) -> int:
        now = observed_at or datetime.now(UTC).isoformat()
        rows = []
        for bar in bars:
            timestamp = bar.get("source_time", bar.get("timestamp", bar.get("time")))
            if not timestamp or bar.get("open") is None or bar.get("high") is None or bar.get("low") is None or bar.get("close") is None:
                continue
            rows.append((pillar, provider, str(bar.get("symbol", "")), str(timestamp), float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]), float(bar["volume"]) if bar.get("volume") is not None else None, bar.get("market_session"), now, source))
        with sqlite3.connect(self.path) as conn:
            before = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            return conn.total_changes - before

    def bars(self, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM market_bars WHERE symbol=? AND source_time>? AND source_time<=? ORDER BY source_time", (symbol, start, end))]
