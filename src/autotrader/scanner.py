from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .models import Instrument, MarketBar, ScanCandidate


@dataclass(frozen=True)
class ScannerConfig:
    lookback_bars: int = 20
    minimum_bars: int = 8
    momentum_weight: float = 0.55
    range_weight: float = 0.25
    volume_weight: float = 0.20
    stop_range_multiplier: float = 1.5
    minimum_score: float = 0.0


class CandidateScanner:
    """Fast deterministic filter that ranks instruments before LLM analysis.

    The scanner is intentionally simple and transparent. It does not claim to be
    alpha on its own; its job is to reduce a large universe to a small set of
    candidates worth deeper TradingAgents analysis.
    """

    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or ScannerConfig()

    def rank(
        self,
        histories: dict[Instrument, list[MarketBar]],
        *,
        top_n: int = 10,
    ) -> list[ScanCandidate]:
        candidates: list[ScanCandidate] = []
        for instrument, bars in histories.items():
            candidate = self.score_instrument(instrument, bars)
            if candidate is not None and candidate.score >= self.config.minimum_score:
                candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[: max(top_n, 0)]

    def score_instrument(
        self,
        instrument: Instrument,
        bars: list[MarketBar],
    ) -> ScanCandidate | None:
        if len(bars) < self.config.minimum_bars:
            return None

        window = bars[-self.config.lookback_bars :]
        if any(bar.symbol != instrument.symbol for bar in window):
            raise ValueError("All bars must match the instrument symbol")
        if any(bar.asset_class != instrument.asset_class for bar in window):
            raise ValueError("All bars must match the instrument asset class")

        first = window[0].close
        last = window[-1].close
        momentum_pct = ((last / first) - 1.0) * 100.0

        ranges_pct = [((bar.high - bar.low) / bar.close) * 100.0 for bar in window]
        average_range_pct = mean(ranges_pct)

        volume_ratio: float | None = None
        positive_volumes = [bar.volume for bar in window if bar.volume > 0]
        if len(positive_volumes) >= 3:
            baseline = mean(positive_volumes[:-1]) if len(positive_volumes) > 1 else 0.0
            if baseline > 0:
                volume_ratio = positive_volumes[-1] / baseline

        normalized_momentum = min(abs(momentum_pct) / 10.0, 1.0)
        normalized_range = min(average_range_pct / 5.0, 1.0)
        normalized_volume = 0.0 if volume_ratio is None else min(max(volume_ratio - 1.0, 0.0), 2.0) / 2.0

        score = 100.0 * (
            self.config.momentum_weight * normalized_momentum
            + self.config.range_weight * normalized_range
            + self.config.volume_weight * normalized_volume
        )

        reasons: list[str] = []
        if momentum_pct >= 2.0:
            reasons.append("positive momentum")
        elif momentum_pct <= -2.0:
            reasons.append("negative momentum")
        if average_range_pct >= 2.0:
            reasons.append("elevated range")
        if volume_ratio is not None and volume_ratio >= 1.5:
            reasons.append("elevated volume")

        stop_distance_pct = max(average_range_pct * self.config.stop_range_multiplier, 0.5)
        if momentum_pct >= 0:
            suggested_stop = last * (1.0 - stop_distance_pct / 100.0)
        else:
            suggested_stop = last * (1.0 + stop_distance_pct / 100.0)

        return ScanCandidate(
            instrument=instrument,
            score=score,
            last_price=last,
            momentum_pct=momentum_pct,
            average_range_pct=average_range_pct,
            volume_ratio=volume_ratio,
            suggested_stop=suggested_stop,
            reasons=tuple(reasons),
        )
