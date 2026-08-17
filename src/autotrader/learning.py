from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_PARAMETERS = {"minimum_candidate_score": 5.0, "momentum_only_score": 12.0}
PARAMETER_BOUNDS = {"minimum_candidate_score": (4.0, 8.0), "momentum_only_score": (9.0, 16.0)}
FORBIDDEN_PARAMETERS = {
    "risk_per_trade_pct", "max_daily_loss_pct", "max_peak_drawdown_pct", "pillar_allocations",
    "reconciliation", "emergency_close", "live_mode", "paper_mode",
}


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_learned_parameters(path: str | Path) -> dict[str, float]:
    result = dict(DEFAULT_PARAMETERS)
    source = Path(path)
    if not source.exists():
        return result
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return result
    if not isinstance(raw, dict):
        return result
    for name, bounds in PARAMETER_BOUNDS.items():
        value = _finite(raw.get(name))
        if value is not None and bounds[0] <= value <= bounds[1]:
            result[name] = value
    return result


@dataclass
class RealizedOutcomeLearner:
    ledger_path: str = "var/autotrader/portfolio.db"
    stats_path: str = "var/autotrader/learning/performance_stats.json"
    parameters_path: str = "var/autotrader/learning/learned_parameters.json"
    history_path: str = "var/autotrader/learning/learning_history.jsonl"
    minimum_samples: int = 20
    preferred_samples: int = 30

    def update(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(UTC)
        trades = self._completed_trades()
        pnls = [float(t["realized_pnl"]) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        count = len(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        expectancy = sum(pnls) / count if count else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        stats = {
            "generated_at": now.astimezone(UTC).isoformat(),
            "completed_trades": count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / count if count else 0.0,
            "average_win": sum(wins) / len(wins) if wins else 0.0,
            "average_loss": sum(losses) / len(losses) if losses else 0.0,
            "expectancy": expectancy,
            "profit_factor": None if math.isinf(profit_factor) else profit_factor,
            "cumulative_realized_pnl": sum(pnls),
            "sample_status": "collecting_evidence" if count < self.minimum_samples else ("limited_adaptation" if count < self.preferred_samples else "adaptive"),
            "hard_guardrails_mutable": False,
        }
        self._write_json(self.stats_path, stats)

        params = load_learned_parameters(self.parameters_path)
        changes: list[dict[str, object]] = []
        if count >= self.minimum_samples:
            # Only entry selectivity is adapted here. Risk limits remain outside this module.
            direction = -1.0 if expectancy > 0 and (profit_factor >= 1.1 or math.isinf(profit_factor)) else 1.0
            scale = 0.02 if count < self.preferred_samples else 0.05
            for name in ("minimum_candidate_score", "momentum_only_score"):
                old = params[name]
                low, high = PARAMETER_BOUNDS[name]
                proposed = old * (1.0 + direction * scale)
                max_step = abs(old) * 0.10
                proposed = max(old - max_step, min(old + max_step, proposed))
                new = max(low, min(high, proposed))
                if abs(new - old) > 1e-12:
                    params[name] = round(new, 6)
                    changes.append({
                        "timestamp": now.astimezone(UTC).isoformat(), "parameter": name,
                        "old_value": old, "new_value": params[name], "sample_size": count,
                        "expectancy": expectancy, "profit_factor": stats["profit_factor"],
                        "win_rate": stats["win_rate"], "reason": "bounded realized-outcome adaptation",
                    })
        self._write_json(self.parameters_path, params)
        if changes:
            history = Path(self.history_path)
            history.parent.mkdir(parents=True, exist_ok=True)
            with history.open("a", encoding="utf-8") as handle:
                for change in changes:
                    handle.write(json.dumps(change, sort_keys=True) + "\n")
        return {**stats, "parameters": params, "changes": changes}

    def _completed_trades(self) -> list[dict[str, object]]:
        path = Path(self.ledger_path)
        if not path.exists():
            return []
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT broker, symbol, side, quantity, price, realized_pnl, occurred_at, metadata_json FROM fills WHERE ABS(realized_pnl) > 0 ORDER BY occurred_at"
                ).fetchall()
            except sqlite3.Error:
                return []
        return [dict(row) for row in rows]

    @staticmethod
    def _write_json(path: str | Path, payload: dict[str, object]) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
