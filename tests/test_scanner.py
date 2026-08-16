from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar
from autotrader.scanner import CandidateScanner, ScannerConfig


def bars(symbol: str, closes: list[float], volumes: list[float] | None = None):
    volumes = volumes or [100.0] * len(closes)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MarketBar(
            symbol=symbol,
            asset_class=AssetClass.STOCK,
            timestamp=start + timedelta(days=i),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=volumes[i],
        )
        for i, close in enumerate(closes)
    ]


def test_scanner_ranks_stronger_momentum_first():
    scanner = CandidateScanner(ScannerConfig(minimum_bars=5, lookback_bars=5))
    strong = Instrument("STRONG", AssetClass.STOCK)
    weak = Instrument("WEAK", AssetClass.STOCK)

    ranked = scanner.rank(
        {
            strong: bars("STRONG", [100, 102, 104, 107, 110]),
            weak: bars("WEAK", [100, 100.5, 101, 101.5, 102]),
        },
        top_n=2,
    )

    assert [c.instrument.symbol for c in ranked] == ["STRONG", "WEAK"]
    assert ranked[0].score > ranked[1].score


def test_scanner_detects_volume_expansion():
    scanner = CandidateScanner(ScannerConfig(minimum_bars=5, lookback_bars=5))
    instrument = Instrument("VOL", AssetClass.STOCK)
    candidate = scanner.score_instrument(
        instrument,
        bars("VOL", [100, 101, 102, 103, 104], [100, 100, 100, 100, 300]),
    )

    assert candidate is not None
    assert candidate.volume_ratio is not None
    assert candidate.volume_ratio > 2.0
    assert "elevated volume" in candidate.reasons
