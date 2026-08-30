"""Research-only cross-source fusion. It cannot authorize or place orders."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FusionResult:
    symbol: str
    attention_anomaly: float
    fundamental_context: str
    market_confirmation: str
    squeeze_context: str
    manipulation_risk: float
    liquidity_risk: float
    anomaly_priority: float
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False


class IntelligenceFusionEngine:
    def fuse(self, symbol: str, *, corporate: Mapping[str, object] | None = None,
             crowd: Mapping[str, object] | None = None, market: Mapping[str, object] | None = None,
             structural: Mapping[str, object] | None = None) -> FusionResult:
        corporate, crowd, market, structural = corporate or {}, crowd or {}, market or {}, structural or {}
        attention = float(crowd.get("attention_velocity") or 0.0)
        manipulation = min(1.0, float(crowd.get("author_concentration") or 0.0) + float(crowd.get("promotion_risk") or 0.0))
        confirmation = "CONFIRMED" if float(market.get("relative_volume") or 0.0) > 1.5 else "UNCONFIRMED"
        reasons = ["SOCIAL_ACCELERATION"] if attention > 1.0 else ["NO_SOCIAL_ACCELERATION"]
        if confirmation == "UNCONFIRMED":
            reasons.append("MARKET_NOT_CONFIRMED")
        return FusionResult(symbol, attention, "AVAILABLE" if corporate else "UNKNOWN", confirmation,
                            "ELEVATED" if structural else "UNKNOWN", manipulation, float(market.get("liquidity_risk") or 0.0),
                            max(0.0, attention * (1.0 - manipulation)), tuple(reasons))
