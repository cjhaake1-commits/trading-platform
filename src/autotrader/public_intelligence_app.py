from __future__ import annotations

import argparse
import asyncio
import json

from .derived_intelligence import DerivedIntelligenceEngine
from .public_market_intelligence import (
    PublicIntelligenceCollector,
    PublicIntelligenceStore,
    stream_coinbase_and_bluesky,
)


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
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
