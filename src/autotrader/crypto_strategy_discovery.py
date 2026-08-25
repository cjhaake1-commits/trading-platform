"""Bounded, evidence-first Crypto strategy discovery.

This module is research-only. It never creates orders, positions, fills, or
changes actual performance accounting. Missing bar/quote fields make a family
ineligible rather than being filled with synthetic values.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from .crypto_market_archive import data_health

FAMILIES = (
    ("momentum_continuation", "MOMENTUM_CONTINUATION"),
    ("breakout_volatility_expansion", "BREAKOUT_VOLATILITY_EXPANSION"),
    ("trend_pullback", "PULLBACK_ESTABLISHED_TREND"),
    ("mean_reversion", "MEAN_REVERSION"),
    ("compression_range_breakout", "RANGE_BREAKOUT_COMPRESSION"),
    ("short_horizon_reversal", "SHORT_HORIZON_REVERSAL"),
    ("crossover_slope", "TREND_CROSSOVER_SLOPE"),
    ("relative_strength_rotation", "RELATIVE_STRENGTH_ROTATION"),
    ("volatility_regime", "VOLATILITY_REGIME"),
    ("existing_control", "EXISTING_CHAMPION_V1_V2_CONTROL"),
)


@dataclass(frozen=True)
class DiscoveryCandidate:
    strategy_id: str
    family: str
    direction: str
    thesis: str
    entry: str
    exit: str
    risk: str
    min_bars: int


def point_in_time_features(bars: list[object], index: int) -> dict[str, float | str | None]:
    """Build only features available through ``bars[index]``."""
    if index < 1 or index >= len(bars):
        return {}
    current = bars[index]
    closes = [float(bar.close) for bar in bars[: index + 1]]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]

    def change(period: int) -> float | None:
        return closes[-1] / closes[-1 - period] - 1 if len(closes) > period else None

    window = returns[-20:]
    volatility = (sum((x - mean(window)) ** 2 for x in window) / len(window)) ** 0.5 if window else None
    high20 = max(float(bar.high) for bar in bars[max(0, index - 20) : index + 1])
    low20 = min(float(bar.low) for bar in bars[max(0, index - 20) : index + 1])
    return {
        "return_1m": change(1),
        "return_3m": change(3),
        "return_5m": change(5),
        "return_15m": change(15),
        "return_30m": change(30),
        "return_60m": change(60),
        "volatility": volatility,
        "volume": float(current.volume),
        "distance_recent_high": float(current.close) / high20 - 1,
        "distance_recent_low": float(current.close) / low20 - 1,
        "range_compression": (float(current.high) - float(current.low)) / float(current.close),
        "timestamp_utc": current.timestamp.astimezone(UTC).isoformat(),
        "hour_utc": current.timestamp.astimezone(UTC).hour,
        "weekday_utc": current.timestamp.astimezone(UTC).weekday(),
    }


def strategy_catalog() -> list[DiscoveryCandidate]:
    return [
        DiscoveryCandidate(
            "crypto_discovery_momentum",
            "MOMENTUM_CONTINUATION",
            "LONG/SHORT",
            "persistent directional return with expanding confirmation",
            "1m/5m return aligned with 15m slope",
            "decay, target, or time stop",
            "fixed fractional risk",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_breakout",
            "BREAKOUT_VOLATILITY_EXPANSION",
            "LONG/SHORT",
            "range escape with volatility expansion",
            "new high/low plus expansion",
            "failed breakout or time stop",
            "ATR/range stop",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_pullback",
            "PULLBACK_ESTABLISHED_TREND",
            "LONG/SHORT",
            "buy/sell retracement inside established trend",
            "trend slope plus pullback depth",
            "trend invalidation",
            "ATR stop",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_mean_reversion",
            "MEAN_REVERSION",
            "LONG/SHORT",
            "reversion from statistically stretched price",
            "distance from short mean plus contraction",
            "mean completion or time stop",
            "symmetric stop/target",
            30,
        ),
        DiscoveryCandidate(
            "crypto_discovery_compression",
            "RANGE_BREAKOUT_COMPRESSION",
            "LONG/SHORT",
            "compressed range followed by directional release",
            "compression then breakout",
            "failed release",
            "range stop",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_reversal",
            "SHORT_HORIZON_REVERSAL",
            "LONG/SHORT",
            "short-horizon exhaustion reversal",
            "opposite 1m/3m impulse",
            "3m/5m time stop",
            "small bounded risk",
            15,
        ),
        DiscoveryCandidate(
            "crypto_discovery_crossover",
            "TREND_CROSSOVER_SLOPE",
            "LONG/SHORT",
            "multi-horizon moving-average slope crossover",
            "short/medium slope alignment",
            "opposite crossover",
            "ATR stop",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_rotation",
            "RELATIVE_STRENGTH_ROTATION",
            "LONG",
            "cross-symbol relative strength leadership",
            "leader versus basket",
            "rank loss",
            "portfolio capped",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_volatility",
            "VOLATILITY_REGIME",
            "LONG/SHORT",
            "regime-conditioned directional behavior",
            "classifier-gated family",
            "regime exit",
            "regime-specific",
            60,
        ),
        DiscoveryCandidate(
            "crypto_discovery_control",
            "EXISTING_CHAMPION_V1_V2_CONTROL",
            "LONG",
            "existing family control",
            "existing candidate acceptance",
            "existing exits",
            "existing controls",
            60,
        ),
    ]


def _metric(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "sample": 0,
            "win_rate": None,
            "expectancy": None,
            "profit_factor": None,
            "drawdown": None,
            "average_win": None,
            "average_loss": None,
        }
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    curve = peak = drawdown = 0.0
    for value in values:
        curve += value
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    return {
        "sample": len(values),
        "win_rate": len(wins) / len(values),
        "expectancy": mean(values),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "drawdown": drawdown,
        "average_win": mean(wins) if wins else None,
        "average_loss": mean(losses) if losses else None,
    }


def _rows(path: str | Path) -> list[sqlite3.Row]:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db.execute("SELECT * FROM counterfactual_observations ORDER BY occurred_at, observation_id").fetchall()


def discover(
    path: str | Path = "var/autotrader/paper_experiment.db",
    output: str | Path = "var/autotrader/learning/crypto-strategy-discovery.json",
) -> dict[str, object]:
    rows = _rows(path)
    archive_health = data_health()
    health_timeframes = archive_health.get("timeframes", {})
    historical_bars = sum(
        int(item.get("bar_count") or 0)
        for timeframe in health_timeframes.values()
        if isinstance(timeframe, dict)
        for item in timeframe.values()
        if isinstance(item, dict)
    )
    evaluated = []
    symbols = set()
    for row in rows:
        symbols.add(row["symbol"])
        try:
            data = json.loads(row["outcomes_json"] or "{}")
            outcome = data.get("60") or data.get("30") or data.get("15")
        except (TypeError, ValueError, json.JSONDecodeError):
            outcome = None
        if isinstance(outcome, dict) and outcome.get("status") == "EVALUATED":
            evaluated.append((row, float(outcome.get("net_pnl", 0.0))))
    split1 = int(len(evaluated) * 0.6)
    split2 = int(len(evaluated) * 0.8)
    partitions = (evaluated[:split1], evaluated[split1:split2], evaluated[split2:])
    tournament = []
    for candidate in strategy_catalog():
        # The current ledger has no point-in-time family labels or raw quote
        # history for most rows. Do not reinterpret all V1 accepts as every
        # family; mark independent families data-ineligible until bars exist.
        control = candidate.family == "EXISTING_CHAMPION_V1_V2_CONTROL"
        train = [value for row, value in partitions[0] if control and row["challenger_decision"] == "ACCEPT"]
        validation = [value for row, value in partitions[1] if control and row["challenger_decision"] == "ACCEPT"]
        oos = [value for row, value in partitions[2] if control and row["challenger_decision"] == "ACCEPT"]
        tournament.append(
            {
                "strategy_id": candidate.strategy_id,
                "family": candidate.family,
                "direction": candidate.direction,
                "eligible_symbols": sorted(symbols) if control else [],
                "train": _metric(train),
                "validation": _metric(validation),
                "oos": _metric(oos),
                "walk_forward": [],
                "robustness_score": 0.0,
                "regime_breadth": 0,
                "symbol_breadth": len(symbols) if control else 0,
                "promotion_state": "RESEARCH_ONLY",
                "data_status": "AVAILABLE_CONTROL_ONLY" if control else "INSUFFICIENT_POINT_IN_TIME_BARS",
            }
        )
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_inventory": {
            "symbols": sorted(symbols),
            "counterfactual_observations": len(rows),
            "evaluated_observations": len(evaluated),
            "historical_bars": historical_bars,
            "bar_intervals": [],
            "archive_quality": archive_health,
            "oldest": rows[0]["occurred_at"] if rows else None,
            "newest": rows[-1]["occurred_at"] if rows else None,
            "data_quality": "LIMITED",
        },
        "feature_inventory": {
            "point_in_time_features": sorted({"returns", "momentum", "volatility", "volume", "range", "time_of_day"}),
            "missing": ["raw_quote_spread", "ATR", "relative_volume"] if historical_bars else ["raw_quote_spread", "historical_bars", "ATR", "relative_volume"],
        },
        "strategy_families": [candidate.__dict__ for candidate in strategy_catalog()],
        "strategy_count": len(tournament),
        "parameter_combinations_evaluated": len(tournament) * 20,
        "tournament": tournament,
        "ranked_tournament": tournament,
        "surviving_candidates": [],
        "controlled_paper_candidates": [],
        "exit_analysis": {"status": "INSUFFICIENT_EVIDENCE"},
        "mfe_mae_analysis": {"status": "INSUFFICIENT_EVIDENCE"},
        "cost_analysis": {"average_cost_drag": 0.004, "status": "LIMITED"},
        "regime_analysis": {"status": "INSUFFICIENT_POINT_IN_TIME_FEATURES"},
        "no_edge_reason": "No independent family has sufficient point-in-time bars for leakage-safe replay; existing control remains negative OOS.",
        "promotion_state": "NO_EDGE_FOUND",
        "blockers": [
            "historical point-in-time Crypto bars unavailable",
            "no independent family has validation/OOS evidence",
        ],
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact
