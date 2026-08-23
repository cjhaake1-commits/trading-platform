"""Venue-aware session state; closed sessions are normal, not failures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SessionState:
    pillar: str
    state: str
    session: str
    execution: str
    next_transition: str | None


def _in_window(local: time, start: time, end: time) -> bool:
    return start <= local < end if start <= end else local >= start or local < end


def session_state(pillar: str, now: datetime | None = None) -> SessionState:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    key = pillar.lower().replace(" ", "_")
    if key in {"crypto", "kalshi"}:
        return SessionState(pillar, "OPEN", "CONTINUOUS", "SCANNING", None)
    if key in {"forex", "international"}:
        # Research remains active continuously; venue eligibility is assessed
        # separately by broker/instrument adapters.
        open_now = moment.weekday() < 5
        return SessionState(pillar, "OPEN" if open_now else "CLOSED", "VENUE_SPECIFIC", "SCANNING" if open_now else "WAITING_FOR_SESSION", None)
    local = moment.astimezone(ZoneInfo("America/New_York")).time()
    open_now = moment.weekday() < 5 and _in_window(local, time(9, 30), time(16, 0))
    return SessionState(pillar, "OPEN" if open_now else "CLOSED", "US_EQUITY" if open_now else "CLOSED", "SCANNING" if open_now else "WAITING_FOR_SESSION", None)
