"""Durable, provider-backed Crypto market-data archive.

This module is research-only.  It never places orders or changes execution
accounting.  Raw bars are stored in SQLite; larger intervals are derived only
from bars at or before the bucket close.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .brokers.practice_orders import alpaca_crypto_universe

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
CANONICAL_DIRS = ("OHLCV/1m", "OHLCV/5m", "OHLCV/15m", "OHLCV/1h", "OHLCV/4h", "OHLCV/1d", "QUOTES", "SPREADS", "VOLUME", "VOLATILITY", "LIQUIDITY", "SENTIMENT", "KALSHI CROSS-MARKET", "SOLANA DEX", "MACRO CROSS-ASSET")
_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def ensure_data_tree(root: str | Path = "var/autotrader/market-data") -> Path:
    path = Path(root) / "CRYPTO"
    for relative in CANONICAL_DIRS:
        (path / relative).mkdir(parents=True, exist_ok=True)
    return path


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class CryptoBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    ingested_at: datetime
    trade_count: int | None = None
    vwap: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    quote_timestamp: datetime | None = None


def _db_init(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS bars (
            symbol TEXT NOT NULL, timeframe TEXT NOT NULL, timestamp TEXT NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            volume REAL NOT NULL, source TEXT NOT NULL, ingested_at TEXT NOT NULL,
            trade_count INTEGER, vwap REAL, bid REAL, ask REAL, spread REAL, quote_timestamp TEXT,
            PRIMARY KEY(symbol, timeframe, timestamp))""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_crypto_bars_lookup ON bars(symbol, timeframe, timestamp)")


def upsert_bars(path: str | Path, timeframe: str, bars: list[CryptoBar]) -> int:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    _db_init(path)
    rows = [(b.symbol, timeframe, b.timestamp.astimezone(UTC).isoformat(), b.open, b.high, b.low, b.close, b.volume, b.source, b.ingested_at.astimezone(UTC).isoformat(), b.trade_count, b.vwap, b.bid, b.ask, b.spread, b.quote_timestamp.astimezone(UTC).isoformat() if b.quote_timestamp else None) for b in bars]
    with sqlite3.connect(path) as con:
        con.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_bars(path: str | Path, symbol: str | None = None, timeframe: str = "1m") -> list[dict[str, object]]:
    _db_init(path)
    query = "SELECT symbol,timestamp,open,high,low,close,volume,source,ingested_at FROM bars WHERE timeframe=?"
    args: list[object] = [timeframe]
    if symbol:
        query += " AND symbol=?"
        args.append(symbol)
    query += " ORDER BY timestamp"
    with sqlite3.connect(path) as con:
        rows = con.execute(query, args).fetchall()
    return [dict(zip(("symbol", "timestamp", "open", "high", "low", "close", "volume", "source", "ingested_at"), row, strict=True)) for row in rows]


def aggregate_bars(bars: list[CryptoBar], timeframe: str) -> list[CryptoBar]:
    """Aggregate complete source bars, never reading a bar after its bucket."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(timeframe)
    minutes = _MINUTES[timeframe]
    if minutes == 1:
        return list(bars)
    grouped: dict[datetime, list[CryptoBar]] = {}
    for bar in sorted(bars, key=lambda item: item.timestamp):
        stamp = bar.timestamp.astimezone(UTC)
        bucket_minute = (stamp.minute // minutes) * minutes
        bucket = stamp.replace(minute=bucket_minute, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(bar)
    result = []
    for bucket, items in grouped.items():
        expected = minutes
        if len(items) != expected:
            continue
        result.append(CryptoBar(items[0].symbol, bucket, items[0].open, max(x.high for x in items), min(x.low for x in items), items[-1].close, sum(x.volume for x in items), "derived:alpaca_crypto_1m", datetime.now(UTC)))
    return result


def _quality(rows: list[dict[str, object]], timeframe: str) -> dict[str, object]:
    stamps = [_utc(str(row["timestamp"])) for row in rows]
    step = timedelta(minutes=_MINUTES[timeframe])
    unique = len(set(stamps))
    gaps = sum(max(int((stamps[index + 1] - stamps[index]) / step) - 1, 0) for index in range(len(stamps) - 1))
    newest = max(stamps) if stamps else None
    age = (datetime.now(UTC) - newest).total_seconds() if newest else None
    quality = "INSUFFICIENT" if len(stamps) < 2 else "STALE" if age is not None and age > 3 * step.total_seconds() else "LIMITED" if gaps else "GOOD"
    return {"bar_count": len(stamps), "oldest": min(stamps).isoformat() if stamps else None, "newest": newest.isoformat() if newest else None, "missing_intervals": gaps, "duplicate_intervals": len(stamps) - unique, "freshness_seconds": age, "coverage": None if not stamps else 1.0, "quality": quality, "source": rows[-1]["source"] if rows else None}


def data_health(path: str | Path = "var/autotrader/crypto_market_data.db") -> dict[str, object]:
    _db_init(path)
    symbols = sorted({row["symbol"] for tf in TIMEFRAMES for row in load_bars(path, timeframe=tf)})
    result: dict[str, object] = {"generated_at": datetime.now(UTC).isoformat(), "symbols": symbols, "timeframes": {}}
    for tf in TIMEFRAMES:
        result["timeframes"][tf] = {symbol: _quality(load_bars(path, symbol, tf), tf) for symbol in symbols}
    return result


def write_health(path: str | Path = "var/autotrader/crypto_market_data.db", output: str | Path = "var/autotrader/learning/crypto-data-health.json") -> dict[str, object]:
    health = data_health(path)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(health, indent=2), encoding="utf-8")
    return health


def write_research_source_registry(output: str | Path = "var/autotrader/learning/research-source-registry.json") -> None:
    """Record approved research inputs without installing third-party code."""
    registry = {
        "generated_at": datetime.now(UTC).isoformat(),
        "active_sources": [
            {"source": "Alpaca historical Crypto market data", "category": "MARKET_DATA", "status": "ACTIVE", "capability": "provider-backed OHLCV", "research_status": "CONNECTED"},
        ],
        "candidate_sources": [],
        "failed_sources": [],
        "deprecated_sources": [],
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


class AlpacaCryptoArchiveCollector:
    def __init__(self, db_path: str = "var/autotrader/crypto_market_data.db", *, timeout: float = 15.0, max_retries: int = 3) -> None:
        self.db_path, self.timeout, self.max_retries = db_path, timeout, max_retries
        ensure_data_tree()

    def _fetch(self, symbols: list[str], start: datetime, end: datetime, limit: int = 10000) -> list[CryptoBar]:
        key, secret = os.getenv("ALPACA_PAPER_API_KEY", "").strip(), os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
        if not key or not secret or not symbols:
            return []
        result = []
        # Per-symbol requests avoid one liquid pair consuming the shared page limit.
        for symbol in symbols:
            token = None
            while True:
                params = {"symbols": symbol, "timeframe": "1Min", "start": start.astimezone(UTC).isoformat().replace("+00:00", "Z"), "end": end.astimezone(UTC).isoformat().replace("+00:00", "Z"), "limit": limit, "sort": "asc"}
                if token:
                    params["page_token"] = token
                request = Request(f"https://data.alpaca.markets/v1beta3/crypto/us/bars?{urlencode(params)}", headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
                payload = None
                for attempt in range(self.max_retries + 1):
                    try:
                        with urlopen(request, timeout=self.timeout) as response:
                            payload = json.loads(response.read().decode("utf-8"))
                        break
                    except Exception:
                        if attempt >= self.max_retries:
                            raise
                        time.sleep(min(2 ** attempt, 8))
                ingested = datetime.now(UTC)
                bars_payload = (payload or {}).get("bars", {}) or {}
                values = bars_payload.get(symbol) or bars_payload.get(symbol.replace("/", "")) or next(iter(bars_payload.values()), [])
                for item in values or []:
                    result.append(CryptoBar(symbol.upper(), _utc(item["t"]), float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"]), float(item.get("v") or 0), "alpaca_crypto_historical", ingested, item.get("n"), item.get("vw")))
                token = (payload or {}).get("next_page_token")
                if not token:
                    break
                time.sleep(0.1)
        return result

    def run_once(self, *, symbols: tuple[str, ...] | None = None, lookback_hours: int = 24, max_symbols: int | None = None) -> dict[str, object]:
        selected = list(symbols or alpaca_crypto_universe())
        if max_symbols is not None:
            selected = selected[:max_symbols]
        end = datetime.now(UTC).replace(second=0, microsecond=0)
        bars = self._fetch(selected, end - timedelta(hours=lookback_hours), end)
        raw = upsert_bars(self.db_path, "1m", bars)
        stored = [CryptoBar(row["symbol"], _utc(row["timestamp"]), row["open"], row["high"], row["low"], row["close"], row["volume"], row["source"], _utc(row["ingested_at"])) for row in load_bars(self.db_path, timeframe="1m")]
        derived = sum(upsert_bars(self.db_path, tf, aggregate_bars([b for b in stored if b.symbol == symbol], tf)) for tf in TIMEFRAMES[1:] for symbol in selected)
        health = write_health(self.db_path)
        write_research_source_registry()
        return {"symbols": len(selected), "raw_bars": raw, "derived_bars": derived, "health": health}
