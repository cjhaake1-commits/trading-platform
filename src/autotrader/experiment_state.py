from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_EXPERIMENT_ID = "five_pillar_paper_v2"
DEFAULT_EXPERIMENT_PATH = Path("var/autotrader/experiment.json")


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


def load_experiment_state(path: str | Path = DEFAULT_EXPERIMENT_PATH) -> dict[str, str]:
    resolved = Path(path)
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
    resolved = Path(path)
    state = load_experiment_state(resolved)
    if not resolved.exists():
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def _default_experiment_state() -> ExperimentState:
    now = datetime.now(UTC).isoformat()
    return ExperimentState(
        experiment_id=DEFAULT_EXPERIMENT_ID,
        baseline_start_time=now,
        created_at=now,
    )
