"""Versioned paper strategy registry and evidence-gated scorecards.

This module is deliberately provider-agnostic.  Registration and scorecard
updates are research metadata only; they cannot submit, resize, or enable an
order.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    pillar: str
    version: str
    description: str
    timeframe: str
    required_data: tuple[str, ...]
    risk_profile: str
    capital_limit: float
    minimum_sample_size: int = 30
    status: str = "EXPERIMENTAL"


@dataclass
class StrategyScorecard:
    strategy_id: str
    observations: int = 0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown: float = 0.0
    updated_at: str | None = None

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.trades if self.trades else None

    @property
    def expectancy(self) -> float | None:
        return self.realized_pnl / self.trades if self.trades else None

    @property
    def profit_factor(self) -> float | None:
        if self.gross_loss == 0:
            return None if self.gross_profit == 0 else float("inf")
        return self.gross_profit / self.gross_loss

    def record(self, *, outcome: float | None = None, observation: bool = True) -> None:
        if observation:
            self.observations += 1
        if outcome is not None:
            self.trades += 1
            self.realized_pnl += outcome
            if outcome > 0:
                self.wins += 1
                self.gross_profit += outcome
            elif outcome < 0:
                self.losses += 1
                self.gross_loss += abs(outcome)
        self.updated_at = datetime.now(UTC).isoformat()


class StrategyRegistry:
    """Persist definitions and scorecards without coupling them to execution."""

    def __init__(self, path: str | Path = "var/reports/strategy-registry-v1.json") -> None:
        self.path = Path(path)
        self.definitions: dict[str, StrategyDefinition] = {}
        self.scorecards: dict[str, StrategyScorecard] = {}
        self._load()

    def register(self, definition: StrategyDefinition) -> None:
        existing = self.definitions.get(definition.strategy_id)
        if existing and existing.version != definition.version:
            raise ValueError("strategy_id already exists with a different version")
        if definition.capital_limit <= 0 or definition.minimum_sample_size <= 0:
            raise ValueError("strategy capital and sample size must be positive")
        if definition.status not in {"EXPERIMENTAL", "ACTIVE", "PROMOTED", "WATCH", "DEMOTED", "DISABLED"}:
            raise ValueError("invalid strategy status")
        self.definitions[definition.strategy_id] = definition
        self.scorecards.setdefault(definition.strategy_id, StrategyScorecard(definition.strategy_id))
        self.save()

    def record_observation(self, strategy_id: str, *, outcome: float | None = None) -> StrategyScorecard:
        if strategy_id not in self.definitions:
            raise KeyError(strategy_id)
        scorecard = self.scorecards.setdefault(strategy_id, StrategyScorecard(strategy_id))
        scorecard.record(outcome=outcome)
        self.save()
        return scorecard

    def promotion_status(self, strategy_id: str) -> str:
        definition = self.definitions[strategy_id]
        scorecard = self.scorecards[strategy_id]
        if scorecard.observations < definition.minimum_sample_size:
            return "INSUFFICIENT_EVIDENCE"
        if scorecard.expectancy is None or scorecard.expectancy <= 0:
            return "NO_POSITIVE_EXPECTANCY"
        if scorecard.max_drawdown > definition.capital_limit * 0.15:
            return "DRAWDOWN_LIMIT"
        return "ELIGIBLE_FOR_REVIEW"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "registry_id": "STRATEGY_REGISTRY_V1",
            "updated_at": datetime.now(UTC).isoformat(),
            "definitions": [asdict(item) for item in self.definitions.values()],
            "scorecards": [asdict(item) | {
                "win_rate": item.win_rate,
                "expectancy": item.expectancy,
                "profit_factor": item.profit_factor,
            } for item in self.scorecards.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for raw in payload.get("definitions", []):
            raw["required_data"] = tuple(raw.get("required_data", ()))
            definition = StrategyDefinition(**raw)
            self.definitions[definition.strategy_id] = definition
        for raw in payload.get("scorecards", []):
            for derived in ("win_rate", "expectancy", "profit_factor"):
                raw.pop(derived, None)
            scorecard = StrategyScorecard(**raw)
            self.scorecards[scorecard.strategy_id] = scorecard


def default_strategy_definitions() -> tuple[StrategyDefinition, ...]:
    pillars = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
    strategies = ("MOMENTUM", "BREAKOUT", "MEAN_REVERSION", "TREND_FOLLOWING", "RELATIVE_STRENGTH")
    extras = {
        "Forex": ("SESSION_MOMENTUM",),
        "Metals": ("VOLATILITY_EXPANSION",),
    }
    return tuple(
        StrategyDefinition(
            strategy_id=f"{pillar.lower().replace(' ', '_')}.{strategy.lower()}",
            pillar=pillar,
            version="v1",
            description=f"{strategy.replace('_', ' ').title()} research strategy",
            timeframe="15m",
            required_data=("market_data", "quotes"),
            risk_profile="paper_guardrails_v1",
            capital_limit=1000.0,
        )
        for pillar in pillars
        for strategy in (*strategies, *extras.get(pillar, ()))
    )


__all__ = ["StrategyDefinition", "StrategyRegistry", "StrategyScorecard", "default_strategy_definitions"]
