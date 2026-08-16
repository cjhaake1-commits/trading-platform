from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RelayKind(StrEnum):
    MARKET_DATA = "market_data"
    NEWS = "news"
    FILINGS = "filings"
    MACRO = "macro"
    OFFICIAL = "official"
    ALTERNATIVE = "alternative"
    SOCIAL = "social"
    DERIVATIVES = "derivatives"


@dataclass(frozen=True)
class RelaySpec:
    name: str
    kind: RelayKind
    streaming: bool
    expected_max_age_seconds: float
    priority: int
    enabled: bool = True
    license_required: bool = False
    notes: str = ""


@dataclass
class RelayState:
    spec: RelaySpec
    last_received_at: datetime | None = None
    last_source_at: datetime | None = None
    last_latency_ms: float | None = None
    error_count: int = 0
    message_count: int = 0
    last_error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class RelayRegistry:
    """Health/provenance registry for real-time information relays."""

    def __init__(self, specs: list[RelaySpec] | None = None):
        self._states: dict[str, RelayState] = {}
        for spec in specs or default_relay_specs():
            self._states[spec.name] = RelayState(spec=spec)

    def observe(
        self,
        name: str,
        *,
        received_at: datetime | None = None,
        source_at: datetime | None = None,
        latency_ms: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        state = self._states[name]
        state.last_received_at = received_at or datetime.now(UTC)
        state.last_source_at = source_at
        state.last_latency_ms = latency_ms
        state.message_count += 1
        state.last_error = None
        if metadata:
            state.metadata.update(metadata)

    def record_error(self, name: str, error: str) -> None:
        state = self._states[name]
        state.error_count += 1
        state.last_error = error

    def status(self, name: str, *, now: datetime | None = None) -> dict[str, object]:
        state = self._states[name]
        current = now or datetime.now(UTC)
        age_seconds = None
        if state.last_received_at is not None:
            age_seconds = max((current - state.last_received_at).total_seconds(), 0.0)
        fresh = age_seconds is not None and age_seconds <= state.spec.expected_max_age_seconds
        return {
            "name": state.spec.name,
            "kind": state.spec.kind.value,
            "enabled": state.spec.enabled,
            "streaming": state.spec.streaming,
            "priority": state.spec.priority,
            "fresh": fresh,
            "age_seconds": age_seconds,
            "last_latency_ms": state.last_latency_ms,
            "message_count": state.message_count,
            "error_count": state.error_count,
            "last_error": state.last_error,
            "license_required": state.spec.license_required,
            "notes": state.spec.notes,
        }

    def all_status(self, *, now: datetime | None = None) -> list[dict[str, object]]:
        return [
            self.status(name, now=now)
            for name in sorted(
                self._states,
                key=lambda item: (self._states[item].spec.priority, item),
            )
        ]

    def healthy_enabled(self, *, now: datetime | None = None) -> list[str]:
        return [
            status["name"]
            for status in self.all_status(now=now)
            if status["enabled"] and status["fresh"]
        ]


def default_relay_specs() -> list[RelaySpec]:
    """Default relay map ordered by operational importance."""

    return [
        RelaySpec(
            "alpaca_market_stream",
            RelayKind.MARKET_DATA,
            streaming=True,
            expected_max_age_seconds=5.0,
            priority=1,
            notes="Primary U.S. equity/ETF paper market-data relay; feed tier is account dependent.",
        ),
        RelaySpec(
            "oanda_pricing_stream",
            RelayKind.MARKET_DATA,
            streaming=True,
            expected_max_age_seconds=12.0,
            priority=1,
            notes="Primary practice FX pricing/heartbeat relay.",
        ),
        RelaySpec(
            "sec_edgar_current_filings",
            RelayKind.FILINGS,
            streaming=False,
            expected_max_age_seconds=60.0,
            priority=2,
            notes="Poll official SEC current-filings/structured-data endpoints with availability timestamps.",
        ),
        RelaySpec(
            "federal_reserve_official",
            RelayKind.OFFICIAL,
            streaming=False,
            expected_max_age_seconds=120.0,
            priority=2,
            notes="Federal Reserve statements, releases, and official feeds; retain event timestamps.",
        ),
        RelaySpec(
            "bls_macro_releases",
            RelayKind.MACRO,
            streaming=False,
            expected_max_age_seconds=300.0,
            priority=2,
            notes="BLS public data/release information for labor and inflation events.",
        ),
        RelaySpec(
            "bea_macro_releases",
            RelayKind.MACRO,
            streaming=False,
            expected_max_age_seconds=300.0,
            priority=2,
            notes="BEA official API/releases for GDP, income, trade and related macro data.",
        ),
        RelaySpec(
            "fred_alfred",
            RelayKind.MACRO,
            streaming=False,
            expected_max_age_seconds=900.0,
            priority=3,
            notes="Macro series and vintage-aware research; ALFRED supports anti-lookahead tests.",
        ),
        RelaySpec(
            "licensed_breaking_news",
            RelayKind.NEWS,
            streaming=True,
            expected_max_age_seconds=10.0,
            priority=2,
            enabled=False,
            license_required=True,
            notes="Enable only after selecting and licensing a low-latency breaking-news provider.",
        ),
        RelaySpec(
            "licensed_derivatives_intelligence",
            RelayKind.DERIVATIVES,
            streaming=True,
            expected_max_age_seconds=15.0,
            priority=3,
            enabled=False,
            license_required=True,
            notes=(
                "Options/futures positioning, unusual activity, volatility and flow; "
                "license and incremental-edge test required."
            ),
        ),
        RelaySpec(
            "licensed_social_stream",
            RelayKind.SOCIAL,
            streaming=True,
            expected_max_age_seconds=30.0,
            priority=4,
            enabled=False,
            license_required=True,
            notes="Curated social relay only where terms permit automated commercial use.",
        ),
        RelaySpec(
            "quiver_alternative_data",
            RelayKind.ALTERNATIVE,
            streaming=False,
            expected_max_age_seconds=3600.0,
            priority=4,
            enabled=False,
            license_required=True,
            notes=(
                "Political/institutional/public-record context. Use disclosure/publication time, "
                "not transaction date, for backtests."
            ),
        ),
    ]
