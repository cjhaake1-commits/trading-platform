"""Bounded high-velocity PAPER research engines.

These engines produce auditable candidates and simulations. They never use
live endpoints, wallets, private keys, or synthetic derivative capability.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class MicroCandidate:
    symbol: str
    pillar: str
    direction: str
    strategy: str
    timeframe: str
    signal_strength: float
    confidence: float
    expected_gross_edge: float
    estimated_costs: float
    expected_net_edge: float
    expected_holding_minutes: int
    capital_requested: float
    mode: str = "MICRO"


def micro_candidate(
    *,
    symbol: str,
    pillar: str,
    direction: str,
    strategy: str,
    timeframe: str,
    signal_strength: float,
    expected_gross_edge: float,
    costs: float,
    pillar_capital: float = 1000.0,
) -> MicroCandidate | None:
    net = expected_gross_edge - costs
    if net <= 0 or signal_strength <= 0:
        return None
    capital = min(max(pillar_capital * 0.10, 0.0), pillar_capital * 0.15)
    return MicroCandidate(
        symbol,
        pillar,
        direction,
        strategy,
        timeframe,
        signal_strength,
        min(max(signal_strength, 0.0), 1.0),
        expected_gross_edge,
        costs,
        net,
        {"5m": 30, "15m": 60, "30m": 120, "1h": 240}.get(timeframe, 60),
        capital,
    )


def short_candidate(
    *,
    symbol: str,
    pillar: str,
    strategy: str,
    timeframe: str,
    shortable: bool,
    signal_strength: float,
    expected_gross_edge: float,
    costs: float,
) -> MicroCandidate | None:
    if not shortable:
        return None
    return micro_candidate(
        symbol=symbol,
        pillar=pillar,
        direction="SHORT",
        strategy=strategy,
        timeframe=timeframe,
        signal_strength=signal_strength,
        expected_gross_edge=expected_gross_edge,
        costs=costs,
    )


@dataclass(frozen=True)
class ExecutionDecision:
    action: str
    reason: str
    capital_used: float = 0.0


def coordinate(
    candidate: MicroCandidate | None,
    *,
    available_capital: float,
    paper_environment: bool,
    live_trading_enabled: bool = False,
) -> ExecutionDecision:
    if candidate is None:
        return ExecutionDecision("REJECT", "no positive-net candidate")
    if live_trading_enabled or not paper_environment:
        return ExecutionDecision("REJECT", "paper safety gate failed")
    if candidate.capital_requested > available_capital:
        return ExecutionDecision("REJECT", "insufficient pillar capital")
    return ExecutionDecision("PAPER_EXECUTE", "positive net edge and bounded capital", candidate.capital_requested)


@dataclass(frozen=True)
class DerivativeCapability:
    provider: str
    instrument: str
    product_type: str
    long_supported: bool
    short_supported: bool
    paper_sim_supported: bool
    margin_requirement: float | None
    notional_rules: str
    status: str


def capability_registry(provider_truth: Mapping[str, object]) -> list[DerivativeCapability]:
    rows = []
    for row in provider_truth.get("derivatives", []) if isinstance(provider_truth.get("derivatives"), list) else []:
        if not isinstance(row, dict):
            continue
        rows.append(
            DerivativeCapability(
                str(row.get("provider", "")),
                str(row.get("instrument", "")),
                str(row.get("product_type", "")),
                bool(row.get("long_supported")),
                bool(row.get("short_supported")),
                bool(row.get("paper_sim_supported")),
                float(row["margin_requirement"]) if row.get("margin_requirement") is not None else None,
                str(row.get("notional_rules", "")),
                "AVAILABLE" if row.get("paper_sim_supported") else "UNAVAILABLE",
            )
        )
    return rows


def derivative_simulation(
    capability: DerivativeCapability, *, cash_committed: float, notional: float, modeled_loss: float
) -> dict[str, object]:
    if not capability.paper_sim_supported or modeled_loss < 0 or cash_committed < 0:
        raise ValueError("derivative simulation capability or risk data invalid")
    return {
        "provider": capability.provider,
        "instrument": capability.instrument,
        "product_type": capability.product_type,
        "cash_committed": cash_committed,
        "notional": notional,
        "effective_leverage": notional / cash_committed if cash_committed else None,
        "maximum_modeled_loss": modeled_loss,
        "paper_only": True,
    }


@dataclass(frozen=True)
class ArbitrageObservation:
    pair: str
    buy_venue: str
    sell_venue: str
    size: float
    buy_quote: float
    sell_quote: float
    dex_fees: float
    price_impact: float
    slippage: float
    network_fee: float
    priority_fee: float
    quote_age_ms: float
    latency_ms: float
    gross_edge: float
    net_edge: float
    simulated_profit: float


def arbitrage_observation(
    *,
    pair: str,
    buy_venue: str,
    sell_venue: str,
    size: float,
    buy_quote: float,
    sell_quote: float,
    dex_fees: float,
    price_impact: float,
    slippage: float,
    network_fee: float,
    priority_fee: float,
    quote_age_ms: float,
    latency_ms: float,
) -> ArbitrageObservation:
    gross = (sell_quote - buy_quote) * size
    costs = dex_fees + price_impact + slippage + network_fee + priority_fee
    return ArbitrageObservation(
        pair,
        buy_venue,
        sell_venue,
        size,
        buy_quote,
        sell_quote,
        dex_fees,
        price_impact,
        slippage,
        network_fee,
        priority_fee,
        quote_age_ms,
        latency_ms,
        gross,
        gross - costs,
        gross - costs,
    )


def simulate_arbitrage(obs: ArbitrageObservation) -> dict[str, object] | None:
    if obs.net_edge <= 0 or obs.quote_age_ms > 5000:
        return None
    return {
        **asdict(obs),
        "mode": "ARBITRAGE_RESEARCH",
        "paper_only": True,
        "simulated_fill": True,
        "simulated_pnl": obs.simulated_profit,
    }


def write_research_snapshot(
    *,
    candidates: list[MicroCandidate],
    derivative_rows: list[dict[str, object]],
    arbitrage_rows: list[dict[str, object]],
    output: str | Path = "var/autotrader/learning/high-velocity-research.json",
) -> dict[str, object]:
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "micro_candidates": [asdict(x) for x in candidates],
        "derivatives": derivative_rows,
        "arbitrage": arbitrage_rows,
        "live_trading_enabled": os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
