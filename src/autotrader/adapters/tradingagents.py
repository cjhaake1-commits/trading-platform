from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from autotrader.models import AssetClass, Side, TradeProposal


@dataclass
class TradingAgentsAdapter:
    """Thin wrapper around the pinned TauricResearch/TradingAgents foundation.

    The import is intentionally lazy so the deterministic scanner, strategy,
    risk, and backtest layers can run without LLM/API dependencies.
    """

    debug: bool = False

    def analyze(
        self,
        symbol: str,
        analysis_date: date,
        asset_class: AssetClass,
        market_price: float,
        stop_price: float,
    ) -> TradeProposal | None:
        try:
            from tradingagents.agents.utils.rating import parse_rating
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise RuntimeError(
                "TradingAgents is not installed. Install with: pip install -e '.[tradingagents]'"
            ) from exc

        graph = TradingAgentsGraph(debug=self.debug, config=DEFAULT_CONFIG.copy())
        _, decision = graph.propagate(symbol, analysis_date.isoformat())
        decision_text = str(decision)
        rating = parse_rating(decision_text)

        mapping = {
            "Buy": (Side.BUY, 0.90),
            "Overweight": (Side.BUY, 0.70),
            "Hold": (None, 0.50),
            "Underweight": (Side.SELL, 0.70),
            "Sell": (Side.SELL, 0.90),
        }
        side, confidence = mapping[rating]
        if side is None:
            return None

        return TradeProposal(
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            entry_price=market_price,
            stop_price=stop_price,
            confidence=confidence,
            source=f"TradingAgents:{rating}",
            rationale=decision_text,
        )
