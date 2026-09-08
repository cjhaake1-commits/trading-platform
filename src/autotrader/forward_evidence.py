"""Append-only forward decision evidence with timestamp provenance checks."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCOPES = {"BACKTEST", "HISTORICAL_REPLAY", "SHADOW_COUNTERFACTUAL", "FORWARD_PAPER", "PRACTICE", "SIM", "DEMO"}
FORWARD_ENGINES = {
    "autonomous-paper-trading",
    "oanda-fx-paper-trading",
    "alpaca-metals-paper-trading",
    "saxo-international-paper-trading",
    "kalshi-predictions",
    "kalshi-perps",
}


class ForwardEvidenceLedger:
    def __init__(self, path: str | Path = "var/autotrader/forward-evidence.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS forward_decisions (
              decision_id TEXT PRIMARY KEY, decision_ts TEXT NOT NULL, pillar TEXT NOT NULL,
              engine TEXT NOT NULL, provider TEXT NOT NULL, instrument TEXT NOT NULL,
              strategy TEXT NOT NULL, strategy_version TEXT NOT NULL, model_version TEXT NOT NULL,
              scope TEXT NOT NULL, payload_json TEXT NOT NULL)""")

    def append(self, decision: dict[str, object]) -> str:
        required = (
            "decision_id",
            "decision_ts",
            "pillar",
            "engine",
            "provider",
            "instrument",
            "strategy",
            "strategy_version",
            "model_version",
            "scope",
        )
        missing = [x for x in required if not decision.get(x)]
        if missing:
            raise ValueError("missing forward evidence fields: " + ",".join(missing))
        if decision["scope"] not in SCOPES:
            raise ValueError("invalid evidence scope")
        d = datetime.fromisoformat(str(decision["decision_ts"]).replace("Z", "+00:00"))
        for field in ("data_timestamp", "feature_timestamp", "learning_evidence_timestamp"):
            if decision.get(field):
                t = datetime.fromisoformat(str(decision[field]).replace("Z", "+00:00"))
                if t > d or (field == "learning_evidence_timestamp" and t >= d):
                    raise ValueError("look-ahead provenance violation: " + field)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO forward_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(decision["decision_id"]),
                    str(decision["decision_ts"]),
                    str(decision["pillar"]),
                    str(decision["engine"]),
                    str(decision["provider"]),
                    str(decision["instrument"]),
                    str(decision["strategy"]),
                    str(decision["strategy_version"]),
                    str(decision["model_version"]),
                    str(decision["scope"]),
                    json.dumps(decision, sort_keys=True, default=str),
                ),
            )
        return str(decision["decision_id"])

    def metrics(self, scope: str = "FORWARD_PAPER") -> dict[str, object]:
        """Return scope-isolated realized evidence; unknowns stay unknown."""
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload_json FROM forward_decisions WHERE scope=?", (scope,)).fetchall()
        payloads = [json.loads(row[0]) for row in rows]
        # Runtime infrastructure heartbeats, reconciliations, UI refreshes,
        # and report jobs are audit events, not independent model decisions.
        payloads = [p for p in payloads if p.get("engine") in FORWARD_ENGINES]
        values = [float(p["realized_pnl"]) for p in payloads if isinstance(p.get("realized_pnl"), (int, float))]
        deployed = sum(
            float(p.get("capital_required") or p.get("allocated_capital") or 0.0)
            for p in payloads
            if isinstance(p.get("realized_pnl"), (int, float))
        )
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return {
            "scope": scope,
            "decisions": len(payloads),
            "completed": len(values),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(values) if values else None,
            "realized_pnl": sum(values) if values else None,
            "expectancy_after_costs": sum(values) / len(values) if values else None,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
            "max_drawdown": drawdown if values else None,
            "deployed_capital": deployed,
            "return_on_deployed_capital": sum(values) / deployed if deployed else None,
        }


def readiness_report(
    *, sample_size: int, minimum_sample: int, expectancy: float | None, drawdown: float | None, integrity_ok: bool
) -> dict[str, object]:
    if not integrity_ok:
        state = "INCONCLUSIVE"
    elif sample_size < minimum_sample:
        state = "INSUFFICIENT_DATA"
    elif expectancy is None or expectancy <= 0:
        state = "NEGATIVE_EDGE" if expectancy is not None else "INCONCLUSIVE"
    elif drawdown is None:
        state = "INCONCLUSIVE"
    else:
        state = "CANDIDATE_FOR_REVIEW"
    return {
        "state": state,
        "sample_size": sample_size,
        "minimum_sample": minimum_sample,
        "expectancy": expectancy,
        "drawdown": drawdown,
        "live_trading_authority": False,
    }
