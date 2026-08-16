from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .models import AssetClass, Instrument, MarketBar


class HistoricalMarketData(Protocol):
    def history(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[MarketBar]: ...


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
            return []

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

            open_price = float(row["Open"])
            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])
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
