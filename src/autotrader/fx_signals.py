from __future__ import annotations

from dataclasses import dataclass

from .models import Instrument, Side, TradeIntent, TradeProposal
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
        return "asia"
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "london_new_york_overlap"
    if 16 <= hour < 21:
        return "new_york"
    return "late_new_york"


def qualify_fx_long(
    instrument: Instrument,
    bars,
    *,
    hour_utc: int,
    scanner: CandidateScanner | None = None,
    strategies: BaselineStrategies | None = None,
    minimum_score: float = 2.5,
) -> FxSignalDecision:
    """Qualify transparent long-side FX setups without equity-style momentum gating.

    FX is intentionally evaluated separately from equities. A mean-reversion BUY
    may be valid with negative recent momentum, so positive momentum is not a hard
    requirement here. Short FX remains disabled until the portfolio/risk/exit
    stack supports negative positions end-to-end.
    """

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

    proposals = (
        strategies.sma_cross(instrument, bars),
        strategies.breakout(instrument, bars),
        strategies.mean_reversion(instrument, bars),
    )
    buys = [proposal for proposal in proposals if proposal is not None and proposal.side is Side.BUY]
    votes = tuple(proposal.source for proposal in buys)

    diagnostic = {
        "symbol": instrument.symbol,
        "session": session,
        "score": round(candidate.score, 3),
        "momentum_pct": round(candidate.momentum_pct, 4),
        "buy_votes": list(votes),
        "qualified": False,
    }

    if not buys:
        diagnostic["reason"] = "no FX long strategy vote"
        return FxSignalDecision(False, candidate.score, None, (), diagnostic)

    # Two independent BUY votes can qualify even if the generic scanner score is
    # modest. One vote still requires a minimum FX-specific score.
    if candidate.score < minimum_score and len(buys) < 2:
        diagnostic["reason"] = f"FX score below threshold ({candidate.score:.2f} < {minimum_score:.2f})"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    # Avoid fighting strong downside momentum unless the long is explicitly a
    # mean-reversion setup. This preserves the useful distinction between a
    # pullback entry and blindly buying a falling pair.
    if candidate.momentum_pct < -0.75 and "mean_reversion" not in votes:
        diagnostic["reason"] = "strong negative momentum without mean-reversion support"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    entry = float(candidate.last_price)
    # A 0.5% reference stop is intentionally tighter than the generic 2% equity
    # baseline and remains bounded by the unchanged portfolio risk engine.
    stop = entry * 0.995
    if entry <= 0 or stop <= 0 or stop >= entry:
        diagnostic["reason"] = "invalid FX entry/stop geometry"
        return FxSignalDecision(False, candidate.score, None, votes, diagnostic)

    confidence = min(0.90, 0.50 + 0.10 * len(votes) + candidate.score / 500.0)
    proposal = TradeProposal(
        instrument.symbol,
        instrument.asset_class,
        Side.BUY,
        entry,
        stop,
        confidence,
        f"fx:{'+'.join(votes)}",
        (
            f"fx_session={session}; scanner_score={candidate.score:.2f}; "
            f"momentum={candidate.momentum_pct:.3f}%; votes={','.join(votes)}"
        ),
        TradeIntent.ENTER,
    )
    diagnostic["qualified"] = True
    diagnostic["reason"] = "FX long setup passed FX-specific qualification"
    diagnostic["stop_price"] = stop
    return FxSignalDecision(True, candidate.score, proposal, votes, diagnostic)
