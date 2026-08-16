from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import PortfolioState, Position


@dataclass(frozen=True)
class ProtectiveRiskPolicy:
    max_peak_drawdown_pct: float = 0.08
    hard_daily_loss_pct: float = 0.02
    hard_weekly_loss_pct: float = 0.05
    trailing_stop_pct: float | None = None
    break_even_trigger_r: float | None = 1.0
    trailing_trigger_r: float | None = 2.0
    trailing_distance_r: float = 1.0


@dataclass(frozen=True)
class ProtectiveAction:
    kind: str
    symbol: str | None
    reason: str
    stop_price: float | None = None


class DrawdownGovernor:
    """Track equity peaks and fail closed when portfolio loss limits are breached."""

    def __init__(self, initial_equity: float, policy: ProtectiveRiskPolicy | None = None):
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self.policy = policy or ProtectiveRiskPolicy()
        self.peak_equity = initial_equity
        self.kill_switch = False
        self.kill_reason: str | None = None

    def observe(self, portfolio: PortfolioState) -> list[ProtectiveAction]:
        actions: list[ProtectiveAction] = []
        self.peak_equity = max(self.peak_equity, portfolio.equity)

        drawdown_pct = 0.0
        if self.peak_equity > 0:
            drawdown_pct = max((self.peak_equity - portfolio.equity) / self.peak_equity, 0.0)

        if drawdown_pct >= self.policy.max_peak_drawdown_pct:
            self._trip(f"peak drawdown reached {drawdown_pct:.2%}")
        elif portfolio.daily_pnl <= -(portfolio.equity * self.policy.hard_daily_loss_pct):
            self._trip("daily loss limit reached")
        elif portfolio.weekly_pnl <= -(portfolio.equity * self.policy.hard_weekly_loss_pct):
            self._trip("weekly loss limit reached")

        if self.kill_switch:
            actions.append(
                ProtectiveAction(
                    kind="kill_switch",
                    symbol=None,
                    reason=self.kill_reason or "risk kill switch active",
                )
            )
        return actions

    def _trip(self, reason: str) -> None:
        self.kill_switch = True
        self.kill_reason = reason

    def reset(self, *, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reset requires an explicit reason")
        self.kill_switch = False
        self.kill_reason = None


class StopManager:
    """Manage protective long stops without loosening risk after entry."""

    def __init__(self, policy: ProtectiveRiskPolicy | None = None):
        self.policy = policy or ProtectiveRiskPolicy()

    def initialize(self, position: Position, opened_at: datetime | None = None) -> None:
        if position.initial_stop_price is None:
            position.initial_stop_price = position.stop_price
        if position.highest_price is None:
            position.highest_price = position.average_price
        if position.opened_at is None:
            position.opened_at = opened_at

    def update_long(self, position: Position, market_price: float) -> ProtectiveAction | None:
        if market_price <= 0:
            raise ValueError("market_price must be positive")
        if position.quantity <= 0:
            return None

        self.initialize(position)
        initial_stop = position.initial_stop_price
        if initial_stop is None or initial_stop >= position.average_price:
            return None

        position.highest_price = max(position.highest_price or market_price, market_price)
        initial_risk = position.average_price - initial_stop
        gain_r = (market_price - position.average_price) / initial_risk
        candidate = position.stop_price
        reasons: list[str] = []

        break_even_trigger = self.policy.break_even_trigger_r
        if break_even_trigger is not None and gain_r >= break_even_trigger:
            candidate = max(candidate, position.average_price)
            reasons.append("break-even protection")

        trailing_trigger = self.policy.trailing_trigger_r
        if trailing_trigger is not None and gain_r >= trailing_trigger:
            r_stop = position.highest_price - initial_risk * self.policy.trailing_distance_r
            candidate = max(candidate, r_stop)
            reasons.append("R-multiple trailing stop")

        trailing_pct = self.policy.trailing_stop_pct
        if trailing_pct is not None:
            if not 0 < trailing_pct < 1:
                raise ValueError("trailing_stop_pct must be between 0 and 1")
            percent_stop = position.highest_price * (1.0 - trailing_pct)
            candidate = max(candidate, percent_stop)
            reasons.append("percentage trailing stop")

        # Stops may tighten, never loosen.
        if candidate > position.stop_price:
            position.stop_price = min(candidate, market_price)
            return ProtectiveAction(
                kind="tighten_stop",
                symbol=position.symbol,
                reason=", ".join(reasons) or "protective stop tightened",
                stop_price=position.stop_price,
            )
        return None

    @staticmethod
    def stop_triggered(position: Position, executable_price: float) -> bool:
        return position.quantity > 0 and executable_price <= position.stop_price
