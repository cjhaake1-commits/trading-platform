from __future__ import annotations

from dataclasses import dataclass

from .models import Instrument, Side, TradeIntent, TradeProposal
from .multi_strategy import aggregate_confluence, evaluate_proposals
from .scanner import CandidateScanner
from .strategies import BaselineStrategies


@dataclass(frozen=True)
class FxSignalDecision:
    qualified: bool
    score: float
    proposal: TradeProposal | None
    votes: tuple[str, ...]
    diagnostic: dict[str, object]


def fx_session(hour_utc: int) -> str:
    hour = hour_utc % 24
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 16:
        return "LONDON_NEW_YORK_OVERLAP"
    if 16 <= hour < 21:
        return "NEW_YORK"
    return "OFF_PEAK"


def _oanda_price_precision(symbol: str) -> int:
    return 3 if symbol.strip().upper().endswith("/JPY") else 5


def _oanda_price(symbol: str, value: float) -> float:
    return round(float(value), _oanda_price_precision(symbol))


def _session_momentum(instrument: Instrument, bars) -> TradeProposal | None:
    """Return a short-horizon session return, distinct from slow ROC momentum."""
    if len(bars) < 4:
        return None
    start = float(bars[-4].close)
    price = float(bars[-1].close)
    change = price / start - 1.0 if start else 0.0
    if change == 0.0:
        return None
    side = Side.BUY if change > 0 else Side.SELL
    stop = price * (0.98 if side is Side.BUY else 1.02)
    return TradeProposal(
        symbol=instrument.symbol,
        asset_class=instrument.asset_class,
        side=side,
        entry_price=price,
        stop_price=_oanda_price(instrument.symbol, stop),
        confidence=0.50,
        source="session_momentum",
        rationale=f"session_roc={change:.4%}",
    )


def qualify_fx_signal(
    instrument: Instrument,
    bars,
    *,
    hour_utc: int,
    scanner: CandidateScanner | None = None,
    strategies: BaselineStrategies | None = None,
    minimum_score: float = 2.5,
) -> FxSignalDecision:
    """Qualify transparent FX long or short setups independently of equity gating."""

    scanner = scanner or CandidateScanner()
    strategies = strategies or BaselineStrategies()
    candidate = scanner.score_instrument(instrument, bars)
    session = fx_session(hour_utc)

    if candidate is None:
        return FxSignalDecision(
            False,
            0.0,
            None,
            (),
            {
                "symbol": instrument.symbol,
                "session": session,
                "qualified": False,
                "reason": "scanner produced no candidate",
            },
        )

    proposal_set = {
        "momentum": strategies.momentum(instrument, bars),
        "session_momentum": _session_momentum(instrument, bars),
        "trend": strategies.sma_cross(instrument, bars),
        "breakout": strategies.breakout(instrument, bars),
        "mean_reversion": strategies.mean_reversion(instrument, bars),
        "trend_following": strategies.trend_following(instrument, bars),
    }
    evaluations = evaluate_proposals(instrument, bars, proposal_set, timeframe="15m", candidate_score=candidate.score)
    confluence = aggregate_confluence(evaluations)
    proposals = tuple(proposal for proposal in proposal_set.values() if proposal is not None)
    buys = [proposal for proposal in proposals if proposal.side is Side.BUY]
    sells = [proposal for proposal in proposals if proposal.side is Side.SELL]

    diagnostic = {
        "symbol": instrument.symbol,
        "session": session,
        "score": round(candidate.score, 3),
        "momentum_pct": round(candidate.momentum_pct, 4),
        "buy_votes": [proposal.source for proposal in buys],
        "sell_votes": [proposal.source for proposal in sells],
        "strategy_evaluations": [evaluation.__dict__ for evaluation in evaluations],
        "confluence": confluence.__dict__,
        "qualified": False,
    }

    if not buys and not sells:
        diagnostic["reason"] = "no FX strategy vote"
        return FxSignalDecision(False, candidate.score, None, (), diagnostic)

    # Prefer the side with more independent strategy votes. On ties, use recent
    # momentum only as a tie-breaker rather than an absolute qualification gate.
    if len(buys) > len(sells):
        side = Side.BUY
        selected = buys
    elif len(sells) > len(buys):
        side = Side.SELL
        selected = sells
    elif candidate.momentum_pct >= 0:
        side = Side.BUY
        selected = buys
    else:
        side = Side.SELL
        selected = sells

    if not selected:
        diagnostic["reason"] = "strategy-vote tie produced no supported side"
        return FxSignalDecision(False, candidate.score, None, (), diagnostic)

    votes = tuple(proposal.source for proposal in selected)
    if candidate.score < minimum_score and len(selected) < 2:
        diagnostic["reason"] = f"FX score below threshold ({candidate.score:.2f} < {minimum_score:.2f})"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    # Avoid taking a one-vote directional trade directly against unusually strong
    # recent momentum. Mean-reversion gets an explicit exception because that is
    # the strategy's purpose.
    if side is Side.BUY and candidate.momentum_pct < -0.75 and "mean_reversion" not in votes:
        diagnostic["reason"] = "strong negative momentum without mean-reversion support"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)
    if side is Side.SELL and candidate.momentum_pct > 0.75 and "mean_reversion" not in votes:
        diagnostic["reason"] = "strong positive momentum without mean-reversion support"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    entry = float(candidate.last_price)
    raw_stop = entry * (0.995 if side is Side.BUY else 1.005)
    stop = _oanda_price(instrument.symbol, raw_stop)
    if entry <= 0 or stop <= 0:
        diagnostic["reason"] = "invalid FX entry/stop geometry"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)
    if side is Side.BUY and stop >= entry:
        diagnostic["reason"] = "long FX stop must be below entry"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)
    if side is Side.SELL and stop <= entry:
        diagnostic["reason"] = "short FX stop must be above entry"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    confidence = min(0.90, 0.50 + 0.10 * len(votes) + candidate.score / 500.0)
    proposal = TradeProposal(
        instrument.symbol,
        instrument.asset_class,
        side,
        entry,
        stop,
        confidence,
        f"fx:{side.value}:{'+'.join(votes)}",
        (
            f"fx_session={session}; side={side.value}; scanner_score={candidate.score:.2f}; "
            f"momentum={candidate.momentum_pct:.3f}%; votes={','.join(votes)}"
        ),
        TradeIntent.ENTER,
    )
    diagnostic["qualified"] = True
    diagnostic["side"] = side.value
    diagnostic["reason"] = "FX setup passed FX-specific qualification"
    diagnostic["stop_price"] = stop
    diagnostic["price_precision"] = _oanda_price_precision(instrument.symbol)
    return FxSignalDecision(True, candidate.score, proposal, votes, diagnostic)


# Backwards-compatible alias for any callers/tests that still import the first
# long-only helper name. It now uses the complete directional qualifier.
def qualify_fx_long(*args, **kwargs) -> FxSignalDecision:
    return qualify_fx_signal(*args, **kwargs)
