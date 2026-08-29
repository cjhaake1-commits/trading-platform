from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean

from .models import Instrument, MarketBar, Side, TradeProposal


@dataclass(frozen=True)
class StrategyConfig:
    fast_window: int = 5
    slow_window: int = 20
    breakout_window: int = 20
    zscore_window: int = 20
    zscore_entry: float = 1.5
    stop_pct: float = 0.02


class BaselineStrategies:
    """Small transparent strategy set used for baseline comparison and scanning.

    These strategies mirror the spirit of the source paper's rule-based
    comparison set (trend/momentum and mean-reversion families) while keeping the
    implementation dependency-free and auditable.
    """

    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()

    def sma_cross(self, instrument: Instrument, bars: list[MarketBar]) -> TradeProposal | None:
        need = max(self.config.fast_window, self.config.slow_window)
        if len(bars) < need:
            return None
        closes = [b.close for b in bars]
        fast = mean(closes[-self.config.fast_window :])
        slow = mean(closes[-self.config.slow_window :])
        price = closes[-1]

        if fast > slow:
            return self._proposal(
                instrument,
                Side.BUY,
                price,
                "sma_cross",
                f"fast={fast:.4f} > slow={slow:.4f}",
            )
        if fast < slow:
            return self._proposal(
                instrument,
                Side.SELL,
                price,
                "sma_cross",
                f"fast={fast:.4f} < slow={slow:.4f}",
            )
        return None

    def breakout(self, instrument: Instrument, bars: list[MarketBar]) -> TradeProposal | None:
        if len(bars) < self.config.breakout_window + 1:
            return None
        current = bars[-1]
        prior = bars[-(self.config.breakout_window + 1) : -1]
        prior_high = max(b.high for b in prior)
        prior_low = min(b.low for b in prior)

        if current.close > prior_high:
            return self._proposal(
                instrument,
                Side.BUY,
                current.close,
                "breakout",
                f"close>{prior_high:.4f}",
            )
        if current.close < prior_low:
            return self._proposal(
                instrument,
                Side.SELL,
                current.close,
                "breakout",
                f"close<{prior_low:.4f}",
            )
        return None

    def mean_reversion(self, instrument: Instrument, bars: list[MarketBar]) -> TradeProposal | None:
        if len(bars) < self.config.zscore_window:
            return None
        closes = [b.close for b in bars[-self.config.zscore_window :]]
        avg = mean(closes)
        # ``statistics.pstdev`` in Python 3.12 can receive provider numeric
        # scalar subclasses whose second-moment accumulator is a float but is
        # still routed through the Fraction fast path.  Normalize explicitly
        # so a valid metals scan cannot disable the persistent job.
        values = [float(close) for close in closes]
        avg = mean(values)
        sigma = sqrt(sum((value - avg) ** 2 for value in values) / len(values))
        if sigma == 0:
            return None
        z = (values[-1] - avg) / sigma
        price = values[-1]

        if z <= -self.config.zscore_entry:
            return self._proposal(
                instrument,
                Side.BUY,
                price,
                "mean_reversion",
                f"z={z:.3f}",
            )
        if z >= self.config.zscore_entry:
            return self._proposal(
                instrument,
                Side.SELL,
                price,
                "mean_reversion",
                f"z={z:.3f}",
            )
        return None

    def _proposal(
        self,
        instrument: Instrument,
        side: Side,
        price: float,
        source: str,
        rationale: str,
    ) -> TradeProposal:
        if side is Side.BUY:
            stop = price * (1.0 - self.config.stop_pct)
        else:
            stop = price * (1.0 + self.config.stop_pct)
        return TradeProposal(
            symbol=instrument.symbol,
            asset_class=instrument.asset_class,
            side=side,
            entry_price=price,
            stop_price=stop,
            confidence=0.50,
            source=source,
            rationale=rationale,
        )
