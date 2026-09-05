"""Fail-closed bridge for new Kalshi Demo forward candidates.

Legacy provider positions are deliberately outside this path.  Predictions
and Perps share the normal runtime execution consumer; this module only
normalizes their candidate evidence and never fabricates a fill.
"""
from __future__ import annotations

from typing import Mapping

from .runtime_execution_consumer import RuntimeExecutionConsumer

PROTECTED = {"UNKNOWN", "LEGACY", "EXTERNAL"}


def forward_record(candidate: Mapping[str, object], *, family: str) -> dict[str, object]:
    family = family.lower()
    if family not in {"predictions", "perps"}:
        raise ValueError("Kalshi family must be predictions or perps")
    ownership = str(candidate.get("ownership") or "PLATFORM_OWNED").upper()
    ticker = str(candidate.get("ticker") or candidate.get("instrument") or "")
    decision_id = str(candidate.get("decision_id") or f"kalshi:{family}:{ticker}")
    edge = float(candidate.get("expected_return_after_costs", candidate.get("net_edge", 0)) or 0)
    return {
        "intent_id": str(candidate.get("intent_id") or decision_id),
        "decision_id": decision_id,
        "trade_id": str(candidate.get("trade_id") or decision_id),
        "pillar": "kalshi",
        "engine": f"kalshi-{family}",
        "instrument": ticker,
        "strategy": str(candidate.get("strategy") or f"KALSHI_{family.upper()}"),
        "direction": str(candidate.get("direction") or "LONG").upper(),
        "execution_mode": "DEMO",
        "qualified_signal": bool(candidate.get("qualified_signal", candidate.get("qualified", False))),
        "expected_return_after_costs": edge,
        "risk_approved": bool(candidate.get("risk_approved", False)),
        "capital_approved": bool(candidate.get("capital_approved", False)),
        "provider_supported": bool(candidate.get("provider_supported", False)),
        "session_allowed": bool(candidate.get("session_allowed", True)),
        "ownership_allowed": ownership == "PLATFORM_OWNED",
        "ownership": ownership,
        "legacy_provider_exposure": bool(candidate.get("legacy_provider_exposure", ownership in PROTECTED)),
        "capital_required": float(candidate.get("capital_required", 0) or 0),
    }


def consume_forward(candidate: Mapping[str, object], *, family: str,
                    consumer: RuntimeExecutionConsumer, adapter=None,
                    now: str = "") -> dict[str, object]:
    record = forward_record(candidate, family=family)
    if record["ownership"] in PROTECTED or record["legacy_provider_exposure"]:
        return consumer._persist(str(record["intent_id"]), "REJECTED", "PROTECTED_OWNERSHIP", record)
    if float(record["expected_return_after_costs"]) <= 0:
        return consumer._persist(str(record["intent_id"]), "REJECTED", "STRATEGY_NOT_QUALIFIED", record)
    return consumer.consume(record, adapter=adapter, now=now)
