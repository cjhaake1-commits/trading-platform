"""Concrete, read-only market scanners used by the Phase 8 runtime.

Quotes are supplied by the configured market-data adapter.  Missing or stale
data produces concrete blocked rows; it never produces a synthetic signal.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable

from .cash_engine import OpportunityCandidate
from .marketdata import YahooHistoricalData
from .models import AssetClass, Instrument

EQUITIES = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD")
CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD")
FOREX = ("EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD")
METALS = ("GLD", "SLV", "USO")


def _candidate(symbol: str, pillar: str, provider: str, direction: str, strategy: str, bars: list[object], *, shortable: bool = False, now: datetime | None = None) -> OpportunityCandidate:
    latest = bars[-1] if bars else None
    close = float(getattr(latest, "close", 0) or 0) if latest else None
    prior = float(getattr(bars[-2], "close", 0) or 0) if len(bars) > 1 else None
    move = (close - prior) / prior if close and prior else None
    fresh = ((now or datetime.now(UTC)) - latest.timestamp).total_seconds() if latest and getattr(latest, "timestamp", None) else None
    if move is None or close is None:
        status = "BLOCKED_PROVIDER"
    elif fresh is not None and fresh > 900:
        status = "STALE_DATA"
    elif direction == "SHORT" and not shortable:
        status = "NOT_SHORTABLE"
    elif abs(move) <= 0.002:
        status = "INSUFFICIENT_EDGE"
    else:
        status = "ELIGIBLE"
    expected = abs(move) * close if move is not None and status == "ELIGIBLE" else None
    return OpportunityCandidate(pillar, provider, symbol, direction, strategy, abs(move) if move is not None else None, expected, 60, close * 0.1 if close else None, close * 0.05 if close else None, close * 0.01 if close else None, 0.001, 1.0 if close else None, abs(move) if move is not None else None, min(abs(move or 0) * 100, 1.0) if move is not None else None, status=status)


def scan_yahoo_universes(*, now: datetime | None = None, history: Callable[..., list[object]] | None = None) -> tuple[list[OpportunityCandidate], dict[str, int]]:
    """Scan concrete liquid instruments through the existing historical adapter."""
    now = now or datetime.now(UTC)
    feed = history or YahooHistoricalData().history
    candidates: list[OpportunityCandidate] = []
    counts = {"stocks_scanned": 0, "crypto_scanned": 0, "forex_pairs_scanned": 0, "metals_scanned": 0, "signals_detected": 0}
    groups = ((EQUITIES, "stocks", "alpaca-paper", AssetClass.STOCK), (CRYPTO, "crypto", "alpaca-paper", AssetClass.CRYPTO), (FOREX, "forex", "oanda-practice", AssetClass.FOREX), (METALS, "metals", "alpaca-metals-paper", AssetClass.STOCK))
    for symbols, pillar, provider, asset_class in groups:
        for symbol in symbols:
            bars = feed(Instrument(symbol, asset_class), now - timedelta(days=3), now, "1h")
            counts[{"stocks": "stocks_scanned", "crypto": "crypto_scanned", "forex": "forex_pairs_scanned", "metals": "metals_scanned"}[pillar]] += 1
            for direction in ("LONG", "SHORT"):
                row = _candidate(symbol, pillar, provider, direction, "MOMENTUM", bars, shortable=pillar == "stocks" and direction == "SHORT", now=now)
                candidates.append(row)
                counts["signals_detected"] += row.status == "ELIGIBLE"
    return candidates, counts
