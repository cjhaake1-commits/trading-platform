from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .audit import SQLiteAuditStore
from .runtime import AutonomousRuntime, JobResult, RunMode, RuntimeConfig


@dataclass
class HeartbeatJob:
    name: str = "health"
    cadence_seconds: float = 30.0

    def run(self, now: datetime) -> JobResult:
        return JobResult(True, "Runtime health check passed", {"timestamp": now.isoformat()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous trading runtime supervisor")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode], default="paper")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    parser.add_argument("--status", default="var/autotrader/status.json")
    parser.add_argument("--heartbeat", type=float, default=1.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RuntimeConfig(
        mode=RunMode(args.mode),
        heartbeat_seconds=args.heartbeat,
        snapshot_path=Path(args.status),
    )
    runtime = AutonomousRuntime(
        jobs=[HeartbeatJob()],
        audit=SQLiteAuditStore(args.audit_db),
        config=config,
        now_factory=lambda: datetime.now(UTC),
    )
    runtime.run_forever()


if __name__ == "__main__":
    main()
