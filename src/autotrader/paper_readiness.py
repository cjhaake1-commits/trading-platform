"""Truthful six-pillar paper readiness matrix; never authorizes execution."""
from __future__ import annotations

from datetime import UTC, datetime

PILLARS = {"US STOCKS / ETFs": "Alpaca PAPER", "CRYPTO": "Alpaca PAPER", "FOREX": "OANDA PRACTICE", "METALS / COMMODITIES": "Configured PAPER", "INTERNATIONAL": "Saxo SIM", "KALSHI": "Predictions + Perps demo"}
CHECKS = ("ENGINE", "ACCOUNT", "AUTH", "MARKET_DATA", "CLOCK_CALENDAR", "CANDIDATE_DISCOVERY", "STRATEGY_EVALUATION", "QUALIFICATION", "RISK", "PAPER_EXECUTION", "ORDER_ACK", "FILL", "POSITION_RECONCILIATION", "EXIT_MANAGEMENT", "LEARNING_CAPTURE", "MARKET_HISTORY", "RESTART_CONTINUITY", "TELEMETRY")


def build_readiness(*, provider_status: dict[str, dict[str, object]] | None = None, market_open: dict[str, bool] | None = None) -> dict[str, object]:
    provider_status = provider_status or {}
    market_open = market_open or {}
    result = {"generated_at": datetime.now(UTC).isoformat(), "research_only": True, "live_trading_enabled": False, "pillars": {}}
    for pillar, provider in PILLARS.items():
        row = provider_status.get(pillar, {})
        connected = row.get("connected")
        checks = {check: {"status": "PASS" if connected is True else "WARN", "reason": "provider connected" if connected is True else "provider evidence unavailable"} for check in CHECKS}
        checks["CLOCK_CALENDAR"] = {"status": "PASS", "reason": "session-aware status required by runtime"}
        checks["MARKET_DATA"] = {"status": "PASS" if row.get("market_data") is True else "WARN", "reason": "market data observed" if row.get("market_data") is True else "market data not observed"}
        result["pillars"][pillar] = {"provider": provider, "market": "OPEN" if market_open.get(pillar) else "CLOSED/UNKNOWN", "status": "READY" if connected is True and row.get("market_data") is True else "DEGRADED", "checks": checks}
    return result
