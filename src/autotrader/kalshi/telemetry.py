from dataclasses import dataclass


@dataclass
class FamilyTelemetry:
    requests: int = 0
    successes: int = 0
    errors: int = 0
    rate_limited: int = 0
    last_latency_ms: float | None = None
    last_success: str | None = None
    last_error: str | None = None
    last_endpoint: str | None = None
    data_freshness: str = "UNKNOWN"
    websocket_state: str = "DISABLED"

