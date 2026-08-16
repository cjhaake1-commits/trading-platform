from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .models import Instrument, MarketBar, ScanCandidate, TradeProposal
from .scanner import CandidateScanner


class ResearchAdapter(Protocol):
    def analyze(
        self,
        symbol: str,
        analysis_date: date,
        asset_class,
        market_price: float,
        stop_price: float,
    ) -> TradeProposal | None: ...


@dataclass(frozen=True)
class ResearchGateConfig:
    top_n: int = 5
    minimum_scanner_score: float = 25.0


@dataclass
class ResearchPipeline:
    scanner: CandidateScanner
    researcher: ResearchAdapter
    config: ResearchGateConfig = ResearchGateConfig()

    def analyze_ranked(
        self,
        histories: dict[Instrument, list[MarketBar]],
        analysis_date: date,
    ) -> list[tuple[ScanCandidate, TradeProposal | None]]:
        ranked = self.scanner.rank(histories, top_n=self.config.top_n)
        results: list[tuple[ScanCandidate, TradeProposal | None]] = []

        for candidate in ranked:
            if candidate.score < self.config.minimum_scanner_score:
                continue
            proposal = self.researcher.analyze(
                symbol=candidate.instrument.symbol,
                analysis_date=analysis_date,
                asset_class=candidate.instrument.asset_class,
                market_price=candidate.last_price,
                stop_price=candidate.suggested_stop,
            )
            results.append((candidate, proposal))

        return results
