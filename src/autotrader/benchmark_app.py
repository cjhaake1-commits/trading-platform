from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark_readiness import (
    BenchmarkReadinessPolicy,
    PaperPerformanceEvidence,
    assess_benchmark_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate paper evidence against diversified market benchmarks"
    )
    parser.add_argument(
        "--evidence",
        default="var/autotrader/benchmark-evidence.json",
        help="JSON file containing normalized paper and benchmark evidence",
    )
    parser.add_argument(
        "--require-paper-edge",
        action="store_true",
        help="Return non-zero unless the evidence reaches PAPER_EDGE_CONFIRMED",
    )
    return parser


def _load_evidence(path: Path) -> PaperPerformanceEvidence:
    if not path.exists():
        return PaperPerformanceEvidence(
            observation_days=0,
            completed_trades=0,
            observed_market_regimes=0,
            data_coverage=0.0,
            strategy_total_return=0.0,
            strategy_max_drawdown=0.0,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark evidence must be a JSON object")
    return PaperPerformanceEvidence(**payload)


def main() -> None:
    args = build_parser().parse_args()
    evidence_path = Path(args.evidence)
    try:
        evidence = _load_evidence(evidence_path)
        assessment = assess_benchmark_readiness(
            evidence,
            BenchmarkReadinessPolicy.from_env(),
        )
        payload = {
            "evidence_path": str(evidence_path),
            "assessment": assessment.as_dict(),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        payload = {
            "evidence_path": str(evidence_path),
            "assessment": {
                "state": "BLOCKED_DATA_INTEGRITY",
                "live_transition_allowed": False,
                "human_approval_required": True,
                "reasons": [f"benchmark evidence could not be loaded: {type(exc).__name__}: {exc}"],
            },
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.require_paper_edge and payload["assessment"]["state"] != "PAPER_EDGE_CONFIRMED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
