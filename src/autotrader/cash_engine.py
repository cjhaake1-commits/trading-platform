"""Paper-only opportunity scoring and verified cash analytics."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping


def capital_velocity_score(realized_pnl: float, capital_deployed: float, hours_deployed: float) -> float | None:
    """Return realized dollars per capital-dollar-hour; open trades are ineligible."""
    if capital_deployed <= 0 or hours_deployed <= 0:
        return None
    return realized_pnl / capital_deployed / hours_deployed


def validate_native_quote(bid: object, ask: object) -> tuple[bool, float | None, str | None]:
    """Validate executable two-sided quote; never clamp invalid sides."""
    try:
        bid_value, ask_value = float(bid), float(ask)
    except (TypeError, ValueError):
        return False, None, "INVALID_QUOTE"
    if bid_value <= 0 or ask_value <= 0 or ask_value < bid_value:
        return False, None, "INVALID_QUOTE"
    return True, ask_value - bid_value, None


@dataclass(frozen=True)
class OpportunityCandidate:
    pillar: str
    provider: str
    instrument: str
    direction: str
    strategy: str
    expected_edge: float | None
    expected_return: float | None
    estimated_holding_minutes: float | None
    capital_required: float | None
    margin_required: float | None
    maximum_loss: float | None
    spread: float | None
    liquidity: float | None
    volatility: float | None
    confidence: float | None
    historical_expectancy: float | None = None
    recent_expectancy: float | None = None
    drawdown_penalty: float = 0.0
    correlation_penalty: float = 0.0
    execution_cost_penalty: float = 0.0
    status: str = "ELIGIBLE"

    @property
    def capital_velocity_score(self) -> float | None:
        if self.expected_return is None or self.capital_required is None or self.estimated_holding_minutes is None:
            return None
        return capital_velocity_score(self.expected_return, self.capital_required, self.estimated_holding_minutes / 60)

    @property
    def final_opportunity_score(self) -> float | None:
        values = (self.expected_return, self.capital_required, self.estimated_holding_minutes, self.confidence, self.liquidity)
        if any(x is None for x in values) or self.capital_required <= 0 or self.estimated_holding_minutes <= 0:
            return None
        edge = self.expected_return / self.capital_required / (self.estimated_holding_minutes / 60)
        evidence = max(0.0, min(1.0, self.confidence)) * max(0.0, min(1.0, self.liquidity))
        penalty = 1 + max(0.0, self.drawdown_penalty) + max(0.0, self.correlation_penalty) + max(0.0, self.execution_cost_penalty)
        return edge * evidence / penalty

    def as_record(self) -> dict[str, object]:
        row = asdict(self)
        row.update(capital_velocity_score=self.capital_velocity_score, final_opportunity_score=self.final_opportunity_score)
        return row


def rank_opportunities(candidates: Iterable[OpportunityCandidate]) -> list[dict[str, object]]:
    rows = [c.as_record() for c in candidates]
    rows.sort(key=lambda x: (x["final_opportunity_score"] is None, -(x["final_opportunity_score"] or 0), x["pillar"], x["instrument"]))
    return rows


def native_candidate_to_runtime_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    """Normalize native scanner output for the existing execution gate."""
    required = ("instrument", "direction", "strategy", "model_expected_edge", "model_expected_return", "estimated_holding_minutes", "capital_required", "maximum_loss", "spread", "confidence", "provider", "data_source")
    result = dict(candidate)
    result["expected_edge"] = candidate.get("model_expected_edge")
    result["expected_return"] = candidate.get("model_expected_return")
    result["holding_time_minutes"] = candidate.get("estimated_holding_minutes")
    result["economic_risk"] = candidate.get("economic_risk", candidate.get("maximum_loss"))
    result["provider_supported"] = str(candidate.get("data_source", "")).startswith(("ALPACA_NATIVE", "OANDA_NATIVE", "KALSHI_NATIVE"))
    result["qualified_signal"] = candidate.get("status") == "ELIGIBLE"
    result["risk_approved"] = all(candidate.get(key) is not None for key in ("entry_reference", "maximum_loss", "capital_required")) and (candidate.get("stop_price", candidate.get("stop")) is not None)
    result["stop_price"] = candidate.get("stop_price", candidate.get("stop"))
    result["target_price"] = candidate.get("target_price", candidate.get("target"))
    capital_required = result.get("capital_required")
    result["capital_approved"] = capital_required is not None and float(capital_required) <= 1000.0
    result["session_allowed"] = True
    result["ownership_allowed"] = True
    result["execution_mode"] = "PAPER" if candidate.get("provider_environment") == "PAPER" else "PRACTICE"
    result["missing_execution_fields"] = [key for key in required if candidate.get(key) is None]
    return result


def anti_whipsaw_block(candidate: Mapping[str, object], recent_exits: Iterable[Mapping[str, object]]) -> str | None:
    """Block an identical immediate re-entry after a stop until signal evidence changes."""
    instrument = str(candidate.get("instrument", "")).upper()
    direction = str(candidate.get("direction", "")).upper()
    strategy = str(candidate.get("strategy", "")).upper()
    for exit_row in reversed(list(recent_exits)):
        if (str(exit_row.get("instrument", exit_row.get("symbol", ""))).upper() == instrument
                and str(exit_row.get("direction", "")).upper() == direction
                and str(exit_row.get("strategy", "")).upper() == strategy
                and str(exit_row.get("exit_reason", "")).upper() in {"STOP", "STOP_BREACH", "RISK_EXIT"}):
            if float(candidate.get("signal_strength", 0) or 0) <= float(exit_row.get("signal_strength", 0) or 0) * 1.25:
                return "STRATEGY_COOLDOWN"
            return None
    return None


def write_opportunity_report(candidates: Iterable[OpportunityCandidate], output: str | Path = "var/reports/aggressive-opportunity-ranking.json") -> Path:
    rows = rank_opportunities(candidates)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "paper_only": True, "live_trading_enabled": False, "kalshi_perps": "DISABLED", "opportunities": rows}, indent=2, sort_keys=True) + "\n")
    return path


def strategy_scorecard(outcomes: Iterable[Mapping[str, object]], *, minimum_sample: int = 30) -> dict[str, object]:
    values = [float(x["realized_pnl"]) for x in outcomes if isinstance(x.get("realized_pnl"), (int, float))]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {"trade_count": len(values), "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(values) if values else None,
            "gross_profit": gp, "gross_loss": gl, "profit_factor": gp / gl if gl else ("INF" if gp else None),
            "expectancy": sum(values) / len(values) if values else None, "realized_return": sum(values),
            "classification": "PROVEN" if len(values) >= minimum_sample and sum(values) > 0 else ("UNDERPERFORMING" if len(values) >= minimum_sample and sum(values) <= 0 else "EXPERIMENTAL")}
