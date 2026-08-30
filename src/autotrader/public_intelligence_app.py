from __future__ import annotations

import argparse
import asyncio
import json
import os

from .derived_intelligence import DerivedIntelligenceEngine
from .intelligence_orchestrator import IntelligenceOrchestrator
from .public_market_intelligence import (
    PublicIntelligenceCollector,
    PublicIntelligenceStore,
    stream_coinbase_and_bluesky,
)
from .research_platform import ResearchStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect lawful public market-intelligence research data")
    parser.add_argument("--db", default="var/autotrader/public-intelligence.db")
    parser.add_argument("--once", action="store_true", help="Run one scheduled public-data collection cycle")
    parser.add_argument("--stream", action="store_true", help="Run Coinbase + Bluesky public research streams")
    parser.add_argument("--derive", action="store_true", help="Compute research-only features from collected observations")
    parser.add_argument("--events", type=int, default=0, help="Stop streaming after this many events; 0 means continuous")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if sum((args.once, args.stream, args.derive)) != 1:
        raise SystemExit("Choose exactly one of --once, --stream, or --derive")
    if args.events < 0:
        raise SystemExit("--events cannot be negative")

    if args.once:
        result = PublicIntelligenceCollector(store=PublicIntelligenceStore(args.db)).collect_once()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    # The stream remains the existing public-data collector; this one bounded
    # research tick adds durable corporate/fusion knowledge without any broker
    # or order interface.  Failures are isolated so a source cannot kill it.
    try:
        research = ResearchStore(os.getenv("GLOBAL_RESEARCH_DB", "var/autotrader/research.db"))
        intelligence = IntelligenceOrchestrator(research)
        intelligence_result = intelligence.run_once()
    except Exception as exc:  # pragma: no cover - defensive service boundary
        intelligence_result = {"state": "DEGRADED", "error": f"{type(exc).__name__}: {exc}", "research_only": True}

    if args.derive:
        result = DerivedIntelligenceEngine(PublicIntelligenceStore(args.db)).run()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    result = asyncio.run(
        stream_coinbase_and_bluesky(
            store_path=args.db,
            max_events=args.events or None,
        )
    )
    result["intelligence"] = intelligence_result
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
