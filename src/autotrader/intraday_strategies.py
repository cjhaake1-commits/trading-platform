"""Cost-aware intraday candidate generation from supplied market features."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping


FAMILIES = ("MOMENTUM", "BREAKOUT", "BREAKDOWN", "OPENING_RANGE_BREAKOUT", "VWAP_RECLAIM", "VWAP_DEVIATION", "MEAN_REVERSION", "TREND_CONTINUATION", "VOLATILITY_EXPANSION", "RELATIVE_STRENGTH")


@dataclass(frozen=True)
class IntradayCandidate:
    pillar: str
    strategy_id: str
    instrument: str
    direction: str
    entry_concept: str
    invalidation: str
    expected_holding_minutes: float
    expected_return: float
    expected_costs: float
    expected_return_after_costs: float
    expected_loss: float
    confidence: float
    liquidity: float
    capital_required: float
    qualification_state: str


def generate_candidate(*, pillar: str, instrument: str, strategy_id: str, features: Mapping[str, object]) -> IntradayCandidate | None:
    """Return a candidate only when the engine supplies finite, positive evidence."""
    if strategy_id not in FAMILIES:
        raise ValueError("unsupported strategy family")
    required = ("expected_return", "expected_costs", "expected_loss", "confidence", "liquidity", "capital_required", "expected_holding_minutes")
    try:
        values = {key: float(features[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        return None
    if any(value != value or value < 0 for value in values.values()) or values["capital_required"] <= 0:
        return None
    net = values["expected_return"] - values["expected_costs"]
    direction = str(features.get("direction") or "UNKNOWN").upper()
    if direction not in {"LONG", "SHORT"} or net <= 0:
        return IntradayCandidate(pillar, strategy_id, instrument, direction, str(features.get("entry_concept") or "UNKNOWN"), str(features.get("invalidation") or "UNKNOWN"), values["expected_holding_minutes"], values["expected_return"], values["expected_costs"], net, values["expected_loss"], values["confidence"], values["liquidity"], values["capital_required"], "REJECTED_NEGATIVE_EXPECTANCY")
    return IntradayCandidate(pillar, strategy_id, instrument, direction, str(features.get("entry_concept") or strategy_id), str(features.get("invalidation") or "UNKNOWN"), values["expected_holding_minutes"], values["expected_return"], values["expected_costs"], net, values["expected_loss"], values["confidence"], values["liquidity"], values["capital_required"], "QUALIFIED")
