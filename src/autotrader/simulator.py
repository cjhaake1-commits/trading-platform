from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .backtest import BacktestMetrics, compute_metrics
from .models import Instrument, MarketBar, PortfolioState, Position, Side, TradeProposal
from .risk import RiskEngine

Strategy = Callable[[Instrument, list[MarketBar]], TradeProposal | None]


@dataclass(frozen=True)
class SimulationConfig:
    initial_cash: float = 1000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.0005
    periods_per_year: int = 252


@dataclass(frozen=True)
class SimulatedFill:
    bar_index: int
    symbol: str
    side: Side
    quantity: float
    price: float
    fees: float
    reason: str


@dataclass
class SimulationResult:
    equity_curve: list[float]
    fills: list[SimulatedFill] = field(default_factory=list)
    metrics: BacktestMetrics | None = None


class WalkForwardSimulator:
    """Single-instrument long-only simulator with next-bar execution.

    Signals are computed using bars available through index i and executed at
    bar i+1 open. This deliberately prevents same-bar look-ahead. Existing
    positions can exit through a stop observed on a future bar or a SELL signal
    executed at the following bar open.
    """

    def __init__(self, risk_engine: RiskEngine, config: SimulationConfig | None = None):
        self.risk_engine = risk_engine
        self.config = config or SimulationConfig()

    def run(
        self,
        instrument: Instrument,
        bars: list[MarketBar],
        strategy: Strategy,
        warmup_bars: int = 20,
    ) -> SimulationResult:
        if len(bars) < warmup_bars + 2:
            raise ValueError("Not enough bars for warmup and walk-forward execution")

        portfolio = PortfolioState(
            equity=self.config.initial_cash,
            cash=self.config.initial_cash,
        )
        fills: list[SimulatedFill] = []
        equity_curve = [self.config.initial_cash]
        pending: TradeProposal | None = None

        for i, bar in enumerate(bars):
            position = portfolio.positions.get(instrument.symbol)

            # Stop-losses are evaluated using only the current bar after the
            # position was opened on an earlier bar.
            if position is not None and bar.low <= position.stop_price:
                exit_price = self._sell_price(position.stop_price)
                self._close_long(portfolio, position, exit_price, i, fills, "stop")
                position = None
                pending = None

            # Execute the prior bar's signal at this bar open.
            if pending is not None:
                if pending.side is Side.BUY and position is None:
                    entry = self._buy_price(bar.open)
                    stop_ratio = pending.stop_price / pending.entry_price
                    proposal = TradeProposal(
                        symbol=pending.symbol,
                        asset_class=pending.asset_class,
                        side=Side.BUY,
                        entry_price=entry,
                        stop_price=entry * stop_ratio,
                        confidence=pending.confidence,
                        source=pending.source,
                        rationale=pending.rationale,
                    )
                    decision = self.risk_engine.evaluate(proposal, portfolio)
                    if decision.approved:
                        quantity = decision.quantity
                        notional = quantity * entry
                        fees = notional * self.config.commission_pct
                        if notional + fees <= portfolio.cash:
                            portfolio.cash -= notional + fees
                            portfolio.positions[instrument.symbol] = Position(
                                symbol=instrument.symbol,
                                asset_class=instrument.asset_class,
                                quantity=quantity,
                                average_price=entry,
                                stop_price=proposal.stop_price,
                            )
                            fills.append(
                                SimulatedFill(
                                    i,
                                    instrument.symbol,
                                    Side.BUY,
                                    quantity,
                                    entry,
                                    fees,
                                    proposal.source,
                                )
                            )
                elif pending.side is Side.SELL and position is not None:
                    exit_price = self._sell_price(bar.open)
                    self._close_long(portfolio, position, exit_price, i, fills, pending.source)
                pending = None

            position = portfolio.positions.get(instrument.symbol)
            marked_equity = portfolio.cash
            if position is not None:
                marked_equity += position.quantity * bar.close
            portfolio.equity = marked_equity
            equity_curve.append(marked_equity)

            if i >= warmup_bars and i < len(bars) - 1:
                pending = strategy(instrument, bars[: i + 1])

        # Close an open position at the final close so metrics are fully realized.
        final_position = portfolio.positions.get(instrument.symbol)
        if final_position is not None:
            final_price = self._sell_price(bars[-1].close)
            self._close_long(
                portfolio,
                final_position,
                final_price,
                len(bars) - 1,
                fills,
                "final_close",
            )
            equity_curve[-1] = portfolio.cash

        metrics = compute_metrics(
            equity_curve,
            periods_per_year=self.config.periods_per_year,
        )
        return SimulationResult(equity_curve=equity_curve, fills=fills, metrics=metrics)

    def _buy_price(self, raw: float) -> float:
        return raw * (1.0 + self.config.slippage_pct)

    def _sell_price(self, raw: float) -> float:
        return raw * (1.0 - self.config.slippage_pct)

    def _close_long(
        self,
        portfolio: PortfolioState,
        position: Position,
        price: float,
        bar_index: int,
        fills: list[SimulatedFill],
        reason: str,
    ) -> None:
        proceeds = position.quantity * price
        fees = proceeds * self.config.commission_pct
        portfolio.cash += proceeds - fees
        portfolio.positions.pop(position.symbol, None)
        fills.append(
            SimulatedFill(
                bar_index,
                position.symbol,
                Side.SELL,
                position.quantity,
                price,
                fees,
                reason,
            )
        )
