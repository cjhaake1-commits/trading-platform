from __future__ import annotations

import argparse
import json

from .brokers.alpaca_metals_paper import AlpacaMetalsConfigurationError, AlpacaMetalsPaperAdapter
from .brokers.connectivity import test_alpaca_paper, test_oanda_practice
from .brokers.saxo_sim import SaxoConfigurationError, SaxoSimAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test broker API connectivity")
    parser.add_argument(
        "--broker",
        choices=["alpaca", "metals", "oanda", "saxo", "all"],
        default="all",
        help="Broker connectivity probe to run",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = []
    failed = False
    if args.broker in {"alpaca", "all"}:
        results.append(test_alpaca_paper())
    if args.broker in {"oanda", "all"}:
        results.append(test_oanda_practice())
    if args.broker in {"metals", "all"}:
        try:
            adapter = AlpacaMetalsPaperAdapter.from_env()
            summary = adapter.account_summary().as_dict()
            summary["currently_tradable_universe"] = list(adapter.tradable_metals())
            print(json.dumps(summary, indent=2, sort_keys=True))
        except (AlpacaMetalsConfigurationError, RuntimeError) as exc:
            print(json.dumps({"broker": "alpaca-metals-paper", "ok": False, "message": str(exc)}, indent=2))
            failed = True
    if args.broker in {"saxo", "all"}:
        try:
            summary = SaxoSimAdapter.from_env().account_summary()
            print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
        except (SaxoConfigurationError, RuntimeError) as exc:
            print(json.dumps({"broker": "saxo-sim", "ok": False, "message": str(exc)}, indent=2))
            failed = True

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
