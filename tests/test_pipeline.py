from datetime import UTC, date, datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar, Side, TradeProposal
from autotrader.pipeline import ResearchGateConfig, ResearchPipeline
from autotrader.scanner import CandidateScanner, ScannerConfig


def bars(symbol: str, closes: list[float]):
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
            volume=1000.0,
        )
        for i, close in enumerate(closes)
    ]


class FakeResearcher:
    def __init__(self):
        self.calls: list[str] = []

    def analyze(self, symbol, analysis_date, asset_class, market_price, stop_price):
        self.calls.append(symbol)
        return TradeProposal(
            symbol=symbol,
            asset_class=asset_class,
            side=Side.BUY,
            entry_price=market_price,
            stop_price=stop_price,
            confidence=0.7,
            source="fake",
        )


def test_pipeline_only_sends_top_ranked_candidates_to_research():
    researcher = FakeResearcher()
    pipeline = ResearchPipeline(
        scanner=CandidateScanner(ScannerConfig(minimum_bars=5, lookback_bars=5)),
        researcher=researcher,
        config=ResearchGateConfig(top_n=1, minimum_scanner_score=0.0),
    )
    strong = Instrument("STRONG", AssetClass.STOCK)
    weak = Instrument("WEAK", AssetClass.STOCK)

    results = pipeline.analyze_ranked(
        {
            strong: bars("STRONG", [100, 102, 104, 107, 110]),
            weak: bars("WEAK", [100, 100.2, 100.4, 100.6, 100.8]),
        },
        date(2026, 1, 5),
    )

    assert len(results) == 1
    assert researcher.calls == ["STRONG"]
