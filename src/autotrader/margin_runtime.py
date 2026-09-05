"""Provider/economic-separated simulated margin accounting."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class MarginState:
    economic_equity: float
    gross_notional: float
    net_notional: float
    long_notional: float
    short_notional: float
    margin_used: float
    margin_available: float
    leverage_ratio: float | None
    platform_limit: float | None
    enabled: bool

    def as_dict(self) -> dict[str, object]: return asdict(self)


def calculate_margin(*, economic_equity: float, long_notional: float, short_notional: float,
                     margin_used: float, platform_limit: float | None, enabled: bool = False) -> MarginState:
    gross = abs(long_notional) + abs(short_notional)
    net = long_notional - short_notional
    ratio = gross / economic_equity if economic_equity > 0 else None
    available = max(economic_equity * platform_limit - margin_used, 0.0) if platform_limit is not None and economic_equity > 0 else 0.0
    effective_enabled = bool(enabled and platform_limit is not None and ratio is not None and ratio <= platform_limit)
    return MarginState(economic_equity, gross, net, long_notional, short_notional, margin_used, available, ratio, platform_limit, effective_enabled)
