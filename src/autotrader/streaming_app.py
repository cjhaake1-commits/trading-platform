from __future__ import annotations

import argparse
import asyncio

from .streaming import stream_alpaca_quotes, stream_oanda_prices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream normalized market quotes")
    parser.add_argument("--broker", choices=["alpaca", "oanda"], required=True)
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    parser.add_argument("--events", type=int, default=20, help="Number of events to print")
    parser.add_argument("--feed", default="iex", help="Alpaca stock feed, e.g. iex or sip")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    if args.events <= 0:
        raise SystemExit("--events must be positive")

    if args.broker == "alpaca":
        asyncio.run(
            stream_alpaca_quotes(
                symbols,
                max_events=args.events,
                feed=args.feed,
                timeout_seconds=args.timeout,
            )
        )
    else:
        stream_oanda_prices(
            symbols,
            max_events=args.events,
            timeout_seconds=args.timeout,
        )


if __name__ == "__main__":
    main()
