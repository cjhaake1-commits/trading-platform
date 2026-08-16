from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from statistics import mean, pstdev

from .low_latency import QuoteSnapshot
from .models import MarketBar


@dataclass(frozen=True)
class TechnicalFeatureConfig:
    rsi_period: int = 14
    atr_period: int = 14
    realized_vol_window: int = 20


@dataclass(frozen=True)
class TechnicalFeatures:
    rsi: float | None
    atr: float | None
    atr_pct: float | None
    realized_vol: float | None
    spread_bps: float | None = None
    bid_ask_imbalance: float | None = None


def compute_technical_features(
    bars: list[MarketBar],
    *,
    quote: QuoteSnapshot | None = None,
    config: TechnicalFeatureConfig | None = None,
) -> TechnicalFeatures:
    cfg = config or TechnicalFeatureConfig()
    if cfg.rsi_period <= 1 or cfg.atr_period <= 1 or cfg.realized_vol_window <= 1:
        raise ValueError("technical feature windows must be greater than one")

    return TechnicalFeatures(
        rsi=rsi(bars, cfg.rsi_period),
        atr=atr(bars, cfg.atr_period),
        atr_pct=atr_percent(bars, cfg.atr_period),
        realized_vol=realized_volatility(bars, cfg.realized_vol_window),
        spread_bps=None if quote is None else quote.spread_bps,
        bid_ask_imbalance=None if quote is None else bid_ask_imbalance(quote),
    )


def rsi(bars: list[MarketBar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    closes = [bar.close for bar in bars[-(period + 1) :]]
    changes = [
        current - previous
        for previous, current in zip(closes[:-1], closes[1:], strict=True)
    ]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def true_ranges(bars: list[MarketBar]) -> list[float]:
    if len(bars) < 2:
        return []
    ranges: list[float] = []
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def atr(bars: list[MarketBar], period: int = 14) -> float | None:
    ranges = true_ranges(bars)
    if len(ranges) < period:
        return None
    return mean(ranges[-period:])


def atr_percent(bars: list[MarketBar], period: int = 14) -> float | None:
    value = atr(bars, period)
    if value is None or not bars or bars[-1].close <= 0:
        return None
    return (value / bars[-1].close) * 100.0


def realized_volatility(bars: list[MarketBar], window: int = 20) -> float | None:
    if len(bars) < window + 1:
        return None
    closes = [bar.close for bar in bars[-(window + 1) :]]
    log_returns = [
        log(current / previous)
        for previous, current in zip(closes[:-1], closes[1:], strict=True)
    ]
    if not log_returns:
        return None
    return pstdev(log_returns) * sqrt(window)


def bid_ask_imbalance(quote: QuoteSnapshot) -> float | None:
    if quote.bid_size is None or quote.ask_size is None:
        return None
    total = quote.bid_size + quote.ask_size
    if total <= 0:
        return None
    return (quote.bid_size - quote.ask_size) / total
