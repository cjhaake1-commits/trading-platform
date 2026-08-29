from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .benchmark_readiness import DEFAULT_BENCHMARKS, BenchmarkDefinition


@dataclass(frozen=True)
class PriceObservation:
    timestamp: str
    adjusted_close: float


@dataclass(frozen=True)
class BenchmarkMarketMetrics:
    key: str
    label: str
    category: str
    public_symbol: str
    bloomberg_security: str | None
    source: str
    first_timestamp: str | None
    last_timestamp: str | None
    observations: int
    returns: Mapping[str, float | None]
    maximum_drawdown: float | None
    state: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class BenchmarkPriceProvider(Protocol):
    source_name: str

    def history(self, symbol: str, *, period: str = "1y", interval: str = "1d") -> Sequence[PriceObservation]: ...


def _return_for_window(prices: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(prices) <= window:
        return None
    start = float(prices[-(window + 1)])
    end = float(prices[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def maximum_drawdown(prices: Sequence[float]) -> float | None:
    clean = [float(value) for value in prices if float(value) > 0]
    if not clean:
        return None
    peak = clean[0]
    worst = 0.0
    for price in clean:
        peak = max(peak, price)
        if peak > 0:
            worst = max(worst, (peak - price) / peak)
    return worst


def summarize_benchmark(
    definition: BenchmarkDefinition,
    observations: Sequence[PriceObservation],
    *,
    source: str,
) -> BenchmarkMarketMetrics:
    ordered = sorted(observations, key=lambda row: row.timestamp)
    prices = [float(row.adjusted_close) for row in ordered if float(row.adjusted_close) > 0]
    if len(prices) < 2:
        return BenchmarkMarketMetrics(
            key=definition.key,
            label=definition.label,
            category=definition.category,
            public_symbol=definition.public_symbol,
            bloomberg_security=definition.bloomberg_security,
            source=source,
            first_timestamp=ordered[0].timestamp if ordered else None,
            last_timestamp=ordered[-1].timestamp if ordered else None,
            observations=len(prices),
            returns={"1d": None, "5d": None, "21d": None, "63d": None, "126d": None, "252d": None},
            maximum_drawdown=maximum_drawdown(prices),
            state="INSUFFICIENT_DATA",
            reason="fewer than two positive adjusted-close observations",
        )

    return BenchmarkMarketMetrics(
        key=definition.key,
        label=definition.label,
        category=definition.category,
        public_symbol=definition.public_symbol,
        bloomberg_security=definition.bloomberg_security,
        source=source,
        first_timestamp=ordered[0].timestamp,
        last_timestamp=ordered[-1].timestamp,
        observations=len(prices),
        returns={
            "1d": _return_for_window(prices, 1),
            "5d": _return_for_window(prices, 5),
            "21d": _return_for_window(prices, 21),
            "63d": _return_for_window(prices, 63),
            "126d": _return_for_window(prices, 126),
            "252d": _return_for_window(prices, 252),
        },
        maximum_drawdown=maximum_drawdown(prices),
        state="READY",
        reason="adjusted-close total-return proxy available",
    )


class YFinanceBenchmarkPriceProvider:
    """Public research fallback for benchmark history.

    This provider is not an exchange-grade or licensed institutional feed. It is
    a fallback used to begin paper benchmarking while Bloomberg remains
    unconfigured. Production or commercial use requires a separately reviewed
    licensed source.
    """

    source_name = "yfinance-public-research"

    def history(self, symbol: str, *, period: str = "1y", interval: str = "1d") -> Sequence[PriceObservation]:
        import yfinance as yf

        frame = yf.Ticker(symbol).history(
            period=period,
            interval=interval,
            auto_adjust=True,
            actions=False,
            repair=False,
        )
        if frame is None or getattr(frame, "empty", True):
            return ()
        close = frame.get("Close")
        if close is None:
            return ()
        rows: list[PriceObservation] = []
        for timestamp, value in close.items():
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            stamp = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            rows.append(PriceObservation(timestamp=stamp, adjusted_close=price))
        return tuple(rows)


class BenchmarkTracker:
    def __init__(
        self,
        provider: BenchmarkPriceProvider | None = None,
        benchmarks: Sequence[BenchmarkDefinition] = DEFAULT_BENCHMARKS,
    ) -> None:
        self.provider = provider or YFinanceBenchmarkPriceProvider()
        self.benchmarks = tuple(benchmarks)

    def collect(self, *, period: str = "1y", interval: str = "1d") -> dict[str, object]:
        observed_at = datetime.now(UTC).isoformat()
        results: dict[str, dict[str, object]] = {}
        errors: dict[str, str] = {}
        for definition in self.benchmarks:
            try:
                observations = self.provider.history(
                    definition.public_symbol,
                    period=period,
                    interval=interval,
                )
                metrics = summarize_benchmark(
                    definition,
                    observations,
                    source=self.provider.source_name,
                )
                results[definition.key] = metrics.as_dict()
            except Exception as exc:
                errors[definition.key] = f"{type(exc).__name__}: {exc}"
                results[definition.key] = BenchmarkMarketMetrics(
                    key=definition.key,
                    label=definition.label,
                    category=definition.category,
                    public_symbol=definition.public_symbol,
                    bloomberg_security=definition.bloomberg_security,
                    source=self.provider.source_name,
                    first_timestamp=None,
                    last_timestamp=None,
                    observations=0,
                    returns={"1d": None, "5d": None, "21d": None, "63d": None, "126d": None, "252d": None},
                    maximum_drawdown=None,
                    state="UNAVAILABLE",
                    reason=errors[definition.key],
                ).as_dict()

        ready = sum(1 for row in results.values() if row.get("state") == "READY")
        categories = sorted({definition.category for definition in self.benchmarks})
        return {
            "observed_at": observed_at,
            "source": self.provider.source_name,
            "period": period,
            "interval": interval,
            "benchmark_count": len(self.benchmarks),
            "ready_count": ready,
            "coverage": ready / len(self.benchmarks) if self.benchmarks else 0.0,
            "categories": categories,
            "benchmarks": results,
            "errors": errors,
            "research_only": True,
            "broker_control": False,
        }


def write_benchmark_snapshot(snapshot: Mapping[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(destination)
