from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_EXPERIMENT_ID = "income_6000_v2"
DEFAULT_EXPERIMENT_PATH = Path("var/autotrader/experiment.json")
DEFAULT_PORTFOLIO_PATH = Path("var/autotrader/portfolio.db")


@dataclass(frozen=True)
class ExperimentState:
    experiment_id: str
    baseline_start_time: str
    created_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "experiment_id": self.experiment_id,
            "baseline_start_time": self.baseline_start_time,
            "created_at": self.created_at,
        }


def _parse_state(resolved: Path) -> dict[str, str]:
    if not resolved.exists():
        return _default_experiment_state().as_dict()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return _default_experiment_state().as_dict()
    if not isinstance(payload, dict):
        return _default_experiment_state().as_dict()
    experiment_id = str(payload.get("experiment_id") or DEFAULT_EXPERIMENT_ID).strip()
    baseline_start_time = str(payload.get("baseline_start_time") or "").strip()
    created_at = str(payload.get("created_at") or "").strip()
    if not baseline_start_time:
        baseline_start_time = datetime.now(UTC).isoformat()
    if not created_at:
        created_at = baseline_start_time
    return {
        "experiment_id": experiment_id or DEFAULT_EXPERIMENT_ID,
        "baseline_start_time": baseline_start_time,
        "created_at": created_at,
    }


def _rotate_risk_epoch(resolved: Path, prior: dict[str, str]) -> dict[str, str]:
    """Start the owner-authorized $6k epoch without erasing prior evidence.

    Broker positions, fills and manifests remain untouched. Only the logical
    risk-account P&L/drawdown counters are rebased so losses from a superseded
    capital experiment cannot permanently reject every candidate in the new
    $6,000 / $1,000-per-pillar forward test.
    """
    from .capital_allocations import TOTAL_PAPER_CAPITAL

    now = datetime.now(UTC).isoformat()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    archived: dict[str, object] = {
        **prior,
        "archived_at": now,
        "reason": f"experiment_epoch_rotated_to:{DEFAULT_EXPERIMENT_ID}",
    }
    portfolio_path = resolved.parent / DEFAULT_PORTFOLIO_PATH.name
    if portfolio_path.exists():
        try:
            with sqlite3.connect(portfolio_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM portfolio_state WHERE id=1").fetchone()
                if row is not None:
                    archived["prior_risk_portfolio_state"] = dict(row)
                    connection.execute(
                        """UPDATE portfolio_state
                           SET equity=?, cash=?, daily_pnl=0, weekly_pnl=0,
                               peak_equity=?, updated_at=?
                           WHERE id=1""",
                        (TOTAL_PAPER_CAPITAL, TOTAL_PAPER_CAPITAL, TOTAL_PAPER_CAPITAL, now),
                    )
        except sqlite3.Error as exc:
            archived["risk_epoch_reset_error"] = f"{type(exc).__name__}: {exc}"
    history = resolved.with_name("experiment-history.jsonl")
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(archived, sort_keys=True, default=str) + "\n")
    state = ExperimentState(DEFAULT_EXPERIMENT_ID, now, now).as_dict()
    resolved.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def load_experiment_state(path: str | Path = DEFAULT_EXPERIMENT_PATH) -> dict[str, str]:
    resolved = Path(path)
    state = _parse_state(resolved)
    if resolved.exists() and state.get("experiment_id") != DEFAULT_EXPERIMENT_ID:
        return _rotate_risk_epoch(resolved, state)
    if not resolved.exists():
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def load_experiment_baseline_start(path: str | Path = DEFAULT_EXPERIMENT_PATH) -> datetime:
    state = load_experiment_state(path)
    baseline_start_time = str(state.get("baseline_start_time") or "").strip()
    try:
        parsed = datetime.fromisoformat(baseline_start_time.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def position_is_experiment_eligible(opened_at: datetime | None, baseline_start: datetime) -> bool:
    if opened_at is None:
        return False
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=UTC)
    return opened_at.astimezone(UTC) >= baseline_start.astimezone(UTC)


def ensure_experiment_state(path: str | Path = DEFAULT_EXPERIMENT_PATH) -> dict[str, str]:
    return load_experiment_state(path)


def _default_experiment_state() -> ExperimentState:
    now = datetime.now(UTC).isoformat()
    return ExperimentState(
        experiment_id=DEFAULT_EXPERIMENT_ID,
        baseline_start_time=now,
        created_at=now,
    )
