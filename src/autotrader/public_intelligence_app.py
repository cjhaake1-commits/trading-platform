from __future__ import annotations

import argparse
import asyncio
import json

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
    parser.add_argument("--events", type=int, default=0, help="Stop streaming after this many events; 0 means continuous")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.once == args.stream:
        raise SystemExit("Choose exactly one of --once or --stream")
    if args.events < 0:
        raise SystemExit("--events cannot be negative")

    if args.once:
        result = PublicIntelligenceCollector(store=PublicIntelligenceStore(args.db)).collect_once()
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
