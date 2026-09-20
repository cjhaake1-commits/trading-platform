from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.request import Request, urlopen

from .models import AssetClass, Instrument, MarketBar


def normalize_ohlc(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> tuple[float, float, float, float]:
    """Repair provider rounding anomalies while preserving internal OHLC invariants."""

    return (
        open_price,
        max(open_price, high_price, low_price, close_price),
        min(open_price, high_price, low_price, close_price),
        close_price,
    )


class HistoricalMarketData(Protocol):
    def history(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[MarketBar]: ...


@dataclass
class NativeProviderMarketData:
    """Small bounded native-data adapter used by execution jobs.

    It intentionally has no Yahoo dependency.  Provider failures return an
    empty bounded result and are handled as degraded market data by callers.
    """
    timeout: float = 5.0

    def history(self, instrument: Instrument, start: datetime, end: datetime, interval: str = "1d") -> list[MarketBar]:
        symbol = instrument.symbol
        if instrument.asset_class is AssetClass.FOREX:
            base = os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com").rstrip("/")
            account = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "")
            token = os.getenv("OANDA_PRACTICE_TOKEN", "")
            if not account or not token:
                return []
            granularity = {"5m": "M5", "15m": "M15", "1h": "H1", "1d": "D"}.get(interval, "M5")
            url = f"{base}/v3/instruments/{symbol.replace('/', '_')}/candles?granularity={granularity}&count=100&price=M"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            rows = json.loads(urlopen(Request(url, headers=headers), timeout=self.timeout).read()).get("candles", [])
            values = [(row.get("time"), row.get("mid", {})) for row in rows if row.get("complete")]
        else:
            key, secret = os.getenv("ALPACA_PAPER_API_KEY", ""), os.getenv("ALPACA_PAPER_SECRET_KEY", "")
            if not key or not secret:
                return []
            data_base = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/")
            asset_class = "crypto/us" if instrument.asset_class is AssetClass.CRYPTO else "stocks"
            api_symbol = symbol.replace("/", "%2F")
            timeframe = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}.get(interval, "1Day")
            url = f"{data_base}/v2/{asset_class}/bars?symbols={api_symbol}&timeframe={timeframe}&limit=100"
            headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}
            payload = json.loads(urlopen(Request(url, headers=headers), timeout=self.timeout).read())
            raw = payload.get("bars", {})
            rows = raw.get(symbol) or raw.get(symbol.replace("%2F", "/")) or []
            values = [(row.get("t"), row) for row in rows]
        bars = []
        for timestamp, row in values[-100:]:
            if not timestamp:
                continue
            ts = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            bars.append(MarketBar(symbol=symbol, asset_class=instrument.asset_class, timestamp=ts,
                open=float(row.get("o")), high=float(row.get("h")), low=float(row.get("l")),
                close=float(row.get("c")), volume=float(row.get("v", 0) or 0)))
        return bars


@dataclass(frozen=True)
class YahooSymbolMapper:
    """Translate platform canonical symbols into Yahoo Finance symbols.

    The rules intentionally mirror the supplied TradingAgents source snapshot:
    crypto uses BASE-USD and spot forex uses PAIR=X. Plain equities/ETFs are
    already Yahoo-compatible in most cases.
    """

    aliases: dict[str, str] | None = None

    def to_yahoo(self, instrument: Instrument) -> str:
        custom = self.aliases or {}
        if instrument.symbol in custom:
            return custom[instrument.symbol]

        if instrument.asset_class is AssetClass.CRYPTO:
            return instrument.symbol.replace("/", "-")
        if instrument.asset_class is AssetClass.FOREX:
            return instrument.symbol.replace("/", "") + "=X"
        return instrument.symbol


@dataclass
class YahooHistoricalData:
    mapper: YahooSymbolMapper = YahooSymbolMapper()
    empty_result_ttl_seconds: float = 900.0

    def __post_init__(self) -> None:
        self._empty_until: dict[tuple[str, str], float] = {}

    def history(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[MarketBar]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError(
                "yfinance is not installed. Install with: pip install -e '.[marketdata]'"
            ) from exc

        symbol = self.mapper.to_yahoo(instrument)
        cache_key = (symbol, interval)
        now = time.monotonic()
        if self._empty_until.get(cache_key, 0.0) > now:
            return []
        frame = yf.download(
            symbol,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame is None or frame.empty:
            self._empty_until[cache_key] = now + max(self.empty_result_ttl_seconds, 0.0)
            return []
        self._empty_until.pop(cache_key, None)

        # yfinance can return a MultiIndex for one or many symbols depending on
        # version. Reduce to the requested symbol when required.
        if getattr(frame.columns, "nlevels", 1) > 1:
            try:
                frame = frame.xs(symbol, axis=1, level=1)
            except (KeyError, ValueError):
                frame.columns = [
                    col[0] if isinstance(col, tuple) else col for col in frame.columns
                ]

        bars: list[MarketBar] = []
        for index, row in frame.iterrows():
            timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            else:
                timestamp = timestamp.astimezone(UTC)

            open_price, high_price, low_price, close_price = normalize_ohlc(
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
            )
            volume_value = row["Volume"] if "Volume" in row else 0.0
            volume = float(volume_value) if volume_value == volume_value else 0.0

            bars.append(
                MarketBar(
                    symbol=instrument.symbol,
                    asset_class=instrument.asset_class,
                    timestamp=timestamp,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )
            )

        bars.sort(key=lambda bar: bar.timestamp)
        return bars
