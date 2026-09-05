"""Runtime dispatch for provider-free Crypto counterfactual settlement."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from .paper_experiment import PaperExperimentLedger


def settle_from_runtime(*, bars_by_symbol: Mapping[str, list[object]], now: datetime | None = None,
                        ledger_path: str | Path = "var/autotrader/paper_experiment.db",
                        report_path: str | Path = "var/autotrader/learning/crypto-settlement-runtime.json") -> dict[str, object]:
    ledger = PaperExperimentLedger(ledger_path)
    counts = ledger.resolve_counterfactuals(dict(bars_by_symbol), now=(now or datetime.now(UTC)))
    report = {"updated_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(), "counts": counts, "provider_orders": 0, "side_effects": "NONE"}
    out = Path(report_path); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report
