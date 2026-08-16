from __future__ import annotations

import argparse
import json

from .brokers.connectivity import test_alpaca_paper, test_oanda_practice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test broker API connectivity")
    parser.add_argument(
        "--broker",
        choices=["alpaca", "oanda", "all"],
        default="all",
        help="Broker connectivity probe to run",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = []
    if args.broker in {"alpaca", "all"}:
        results.append(test_alpaca_paper())
    if args.broker in {"oanda", "all"}:
        results.append(test_oanda_practice())

    failed = False
    for result in results:
        print(
            json.dumps(
                {
                    "broker": result.broker,
                    "ok": result.ok,
                    "message": result.message,
                    "details": result.details,
                },
                indent=2,
                sort_keys=True,
            )
        )
        failed = failed or not result.ok

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
