"""Venue-aware session state; closed sessions are normal, not failures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
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


def _next_weekday_open(local: datetime, opening: time, zone: ZoneInfo) -> str:
    candidate = local.replace(hour=opening.hour, minute=opening.minute, second=0, microsecond=0)
    while candidate.weekday() >= 5 or candidate <= local:
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=opening.hour, minute=opening.minute, second=0, microsecond=0)
    return candidate.astimezone(UTC).isoformat()


def _next_fx_open(local: datetime) -> str:
    if local.weekday() == 6 and local.time() < time(17, 0):
        candidate = local.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        days = (6 - local.weekday()) % 7 or 7
        candidate = (local + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    return candidate.astimezone(UTC).isoformat()


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
    next_transition = None if opened else _next_weekday_open(local, time(9, 0) if venue.lower() == "asia" else time(8, 0) if venue.lower() == "uk" else time(9, 0), local.tzinfo)
    return SessionState("International", "OPEN" if opened else "CLOSED", venue.upper(), "SCANNING" if opened else "WAITING_FOR_SESSION", next_transition, venue=venue)


def metals_session_state(instrument: str = "XAU/USD", now: datetime | None = None, *, venue: str = "oanda", broker_open: bool | None = None) -> SessionState:
    if venue.lower().startswith("oanda"):
        opened = fx_is_open(now, broker_open=broker_open)
        local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
        return SessionState("Metals / Commodities", "OPEN" if opened else "CLOSED", "OANDA_METALS", "SCANNING" if opened else "WAITING_FOR_SESSION", None if opened else _next_fx_open(local), venue="oanda", instrument=instrument)
    local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    opened = local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0)
    return SessionState("Metals / Commodities", "OPEN" if opened else "CLOSED", "US_EQUITY_METALS", "SCANNING" if opened else "WAITING_FOR_SESSION", None if opened else _next_weekday_open(local, time(9, 30), NEW_YORK), venue=venue, instrument=instrument)


def session_state(pillar: str, now: datetime | None = None, *, venue: str | None = None, instrument: str | None = None, broker_open: bool | None = None) -> SessionState:
    key = pillar.lower().replace(" ", "_")
    if key in {"crypto", "kalshi"}:
        return SessionState(pillar, "OPEN", "CONTINUOUS", "SCANNING", None)
    if key == "forex":
        opened = fx_is_open(now, broker_open=broker_open)
        local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
        return SessionState(pillar, "OPEN" if opened else "CLOSED", "OANDA_FX", "SCANNING" if opened else "WAITING_FOR_SESSION", None if opened else _next_fx_open(local), venue="oanda")
    if key == "international":
        return international_venue_state(venue or "europe", now, broker_open=broker_open)
    if key in {"metals", "metals_/_commodities", "metals_/commodities"}:
        return metals_session_state(instrument or "XAU/USD", now, venue=venue or "oanda", broker_open=broker_open)
    local = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    opened = local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0)
    return SessionState(pillar, "OPEN" if opened else "CLOSED", "US_EQUITY", "SCANNING" if opened else "WAITING_FOR_SESSION", None if opened else _next_weekday_open(local, time(9, 30), NEW_YORK))
