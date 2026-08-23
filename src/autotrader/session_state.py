"""Venue-aware session state; closed sessions are normal, not failures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SessionState:
    pillar: str
    state: str
    session: str
    execution: str
    next_transition: str | None
    venue: str | None = None
    instrument: str | None = None


def fx_is_open(now: datetime | None = None, *, broker_open: bool | None = None) -> bool:
    if broker_open is not None:
        return broker_open
    local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    weekday, clock = local.weekday(), local.time()
    if weekday == 5:
        return False
    if weekday == 6:
        return clock >= time(17, 0)
    if weekday == 4:
        return clock < time(17, 0)
    return True


def international_venue_state(venue: str, now: datetime | None = None, *, broker_open: bool | None = None) -> SessionState:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    local_zone = {"asia": "Asia/Tokyo", "europe": "Europe/Berlin", "uk": "Europe/London"}.get(venue.lower(), "UTC")
    local = moment.astimezone(ZoneInfo(local_zone))
    if broker_open is not None:
        opened = broker_open
    elif local.weekday() >= 5:
        opened = False
    elif venue.lower() == "asia":
        opened = time(9, 0) <= local.time() < time(15, 30)
    elif venue.lower() == "uk":
        opened = time(8, 0) <= local.time() < time(16, 30)
    else:
        opened = time(9, 0) <= local.time() < time(17, 30)
    return SessionState("International", "OPEN" if opened else "CLOSED", venue.upper(), "SCANNING" if opened else "WAITING_FOR_SESSION", None, venue=venue)


def metals_session_state(instrument: str = "XAU/USD", now: datetime | None = None, *, venue: str = "oanda", broker_open: bool | None = None) -> SessionState:
    if venue.lower().startswith("oanda"):
        opened = fx_is_open(now, broker_open=broker_open)
        return SessionState("Metals / Commodities", "OPEN" if opened else "CLOSED", "OANDA_METALS", "SCANNING" if opened else "WAITING_FOR_SESSION", None, venue="oanda", instrument=instrument)
    local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    opened = local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0)
    return SessionState("Metals / Commodities", "OPEN" if opened else "CLOSED", "US_EQUITY_METALS", "SCANNING" if opened else "WAITING_FOR_SESSION", None, venue=venue, instrument=instrument)


def session_state(pillar: str, now: datetime | None = None, *, venue: str | None = None, instrument: str | None = None, broker_open: bool | None = None) -> SessionState:
    key = pillar.lower().replace(" ", "_")
    if key in {"crypto", "kalshi"}:
        return SessionState(pillar, "OPEN", "CONTINUOUS", "SCANNING", None)
    if key == "forex":
        opened = fx_is_open(now, broker_open=broker_open)
        return SessionState(pillar, "OPEN" if opened else "CLOSED", "OANDA_FX", "SCANNING" if opened else "WAITING_FOR_SESSION", None, venue="oanda")
    if key == "international":
        return international_venue_state(venue or "europe", now, broker_open=broker_open)
    if key in {"metals", "metals_/_commodities", "metals_/commodities"}:
        return metals_session_state(instrument or "XAU/USD", now, venue=venue or "oanda", broker_open=broker_open)
    local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    opened = local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0)
    return SessionState(pillar, "OPEN" if opened else "CLOSED", "US_EQUITY", "SCANNING" if opened else "WAITING_FOR_SESSION", None)
