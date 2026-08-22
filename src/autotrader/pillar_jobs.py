from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .brokers.alpaca_metals_paper import AlpacaMetalsConfigurationError
from .brokers.saxo_sim import SaxoSimAdapter
from .capital_allocations import PILLAR_METALS
from .international_trading import InternationalExecutionService
from .marketdata import YahooHistoricalData
from .metals_trading import MetalsExecutionService
from .models import AssetClass, Instrument, MarketBar, Side
from .runtime import JobResult
from .scanner import CandidateScanner
from .strategies import BaselineStrategies


def _bars_from_saxo(samples, instrument: Instrument) -> list[MarketBar]:
    bars: list[MarketBar] = []
    for sample in samples:
        try:
            timestamp = datetime.fromisoformat(sample.timestamp.replace("Z", "+00:00"))
            bars.append(
                MarketBar(
                    symbol=instrument.symbol,
                    asset_class=instrument.asset_class,
                    timestamp=timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC),
                    open=float(sample.open),
                    high=float(sample.high),
                    low=float(sample.low),
                    close=float(sample.close),
                    volume=float(sample.volume),
                )
            )
        except Exception:
            continue
    return bars


@dataclass
class MetalsPaperTradingJob:
    name: str = "alpaca-metals-paper-trading"
    cadence_seconds: float = 300.0
    history_path: str = "var/autotrader/metals_trades.db"
    universe: tuple[str, ...] = ("GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL")

    def __post_init__(self) -> None:
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        try:
            self.service = MetalsExecutionService.from_env(self.history_path)
        except AlpacaMetalsConfigurationError:
            self.service = None

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if self.service is None:
            return JobResult(
                True,
                "Metals cycle deferred",
                {
                    "pillar": PILLAR_METALS,
                    "reason": "alpaca paper credentials unavailable",
                },
            )
        histories = self._load_histories(now)
        if not histories:
            return JobResult(True, "Metals cycle found no usable market data", {"pillar": PILLAR_METALS})
        best = self._best_signal(histories)
        if best is None:
            return JobResult(True, "Metals cycle found no qualifying entry", {"pillar": PILLAR_METALS})
        return JobResult(
            True,
            "Metals cycle scanned successfully",
            {"pillar": PILLAR_METALS, "candidate": best.instrument.symbol},
        )

    def _load_histories(self, now: datetime) -> dict[Instrument, list[MarketBar]]:
        end = now.astimezone(UTC)
        start = end - timedelta(days=14)
        histories: dict[Instrument, list[MarketBar]] = {}
        for symbol in self.universe:
            instrument = Instrument(symbol, AssetClass.ETF)
            bars = self.feed.history(instrument, start, end)
            histories[instrument] = bars
        return histories

    def _best_signal(self, histories: dict[Instrument, list[MarketBar]]):
        ranked = self.scanner.rank(histories, top_n=1)
        if not ranked:
            return None
        candidate = ranked[0]
        proposal = self.strategies.sma_cross(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            proposal = self.strategies.breakout(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            proposal = self.strategies.mean_reversion(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            return None
        return candidate


@dataclass
class InternationalPaperTradingJob:
    name: str = "saxo-international-paper-trading"
    cadence_seconds: float = 300.0
    history_path: str = "var/autotrader/international_trades.db"
    search_keywords: str = "Stock"
    search_top: int = 5

    def __post_init__(self) -> None:
        try:
            self.adapter = SaxoSimAdapter.from_env()
        except Exception:
            self.adapter = None
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        try:
            self.service = InternationalExecutionService.from_env(self.history_path)
        except Exception:
            self.service = None

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if self.adapter is None or self.service is None:
            return JobResult(
                True,
                "International AUTH REQUIRED",
                {"state": "AUTH REQUIRED", "error": "Saxo SIM credentials unavailable"},
            )
        try:
            instruments = self.adapter.search_instruments(
                self.search_keywords,
                asset_types=("Stock",),
                top=self.search_top,
            )
        except Exception as exc:
            error = str(exc)
            if "401" in error or "unauthorized" in error.lower():
                return JobResult(
                    True,
                    "International AUTH REQUIRED",
                    {"state": "AUTH REQUIRED", "error": "Saxo SIM authentication rejected the read-only probe"},
                )
            return JobResult(True, "International DATA UNAVAILABLE", {"state": "DATA UNAVAILABLE", "error": error})
        if not instruments:
            return JobResult(True, "International cycle found no instruments", {})
        histories: dict[Instrument, list[MarketBar]] = {}
        for item in instruments:
            instrument = Instrument(item.symbol.replace(".", "-"), AssetClass.STOCK)
            try:
                samples = self.adapter.chart_samples(item, count=30)
            except Exception:
                continue
            bars = _bars_from_saxo(samples, instrument)
            if len(bars) >= 8:
                histories[instrument] = bars
        if not histories:
            return JobResult(True, "International cycle found no usable market data", {})
        ranked = self.scanner.rank(histories, top_n=1)
        if not ranked:
            return JobResult(True, "International cycle found no qualifying entry", {})
        return JobResult(True, "International cycle scanned successfully", {"candidate": ranked[0].instrument.symbol})
