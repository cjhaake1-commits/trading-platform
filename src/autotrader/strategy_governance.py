"""Non-p-hacking strategy cohort metrics and governance labels."""

from __future__ import annotations

from typing import Iterable, Mapping


def cohort_metrics(outcomes: Iterable[Mapping[str, object]], *, minimum_validated: int = 30) -> dict[str, object]:
    values = [float(row["realized_pnl"]) for row in outcomes if isinstance(row.get("realized_pnl"), (int, float))]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    expectancy = sum(values) / len(values) if values else None
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    if len(values) < 5:
        label = "UNPROVEN"
    elif expectancy is not None and expectancy < 0:
        label = "NEGATIVE"
    elif len(values) < minimum_validated:
        label = "EARLY_POSITIVE" if expectancy and expectancy > 0 else "UNPROVEN"
    else:
        label = "VALIDATED_PAPER_POSITIVE" if expectancy and expectancy > 0 else "NEGATIVE"
    return {
        "sample_size": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "average_win": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "expectancy_after_costs": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown": drawdown if values else None,
        "label": label,
    }
