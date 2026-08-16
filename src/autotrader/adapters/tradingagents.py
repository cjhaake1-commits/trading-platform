from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from autotrader.models import AssetClass, Side, TradeProposal


@dataclass
class TradingAgentsAdapter:
    """Thin wrapper around TauricResearch/TradingAgents.

    The import is intentionally lazy so the deterministic core and its tests can
    run without requiring LLM/API dependencies.
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
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise RuntimeError(
                "TradingAgents is not installed. Install with: pip install -e '.[tradingagents]'"
            ) from exc

        graph = TradingAgentsGraph(debug=self.debug, config=DEFAULT_CONFIG.copy())
        _, decision = graph.propagate(symbol, analysis_date.isoformat())
        rating = str(decision).strip().lower()

        if "buy" in rating or "overweight" in rating:
            side = Side.BUY
        elif "sell" in rating or "underweight" in rating:
            # Short selling is disabled by default, so this proposal will normally
            # be rejected by the deterministic risk engine during bootstrap.
            side = Side.SELL
        else:
            return None

        return TradeProposal(
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            entry_price=market_price,
            stop_price=stop_price,
            confidence=0.5,
            source="TradingAgents",
            rationale=str(decision),
        )
