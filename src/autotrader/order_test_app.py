from __future__ import annotations

import argparse
import json

from .brokers.practice_orders import (
    submit_alpaca_paper_market_order,
    submit_oanda_practice_market_order,
)


def _print_result(result) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit one explicitly confirmed paper/practice test order"
    )
    parser.add_argument("--broker", required=True, choices=["alpaca", "oanda"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument("--notional", type=float, default=1.0)
    parser.add_argument("--units", type=int, default=1)
    parser.add_argument(
        "--confirm-practice-order",
        action="store_true",
        help="Required acknowledgement that this command submits a simulated broker order",
    )
    args = parser.parse_args()

    if not args.confirm_practice_order:
        parser.error("--confirm-practice-order is required")

    if args.broker == "alpaca":
        result = submit_alpaca_paper_market_order(
            args.symbol,
            side=args.side,
            notional=args.notional,
        )
    else:
        units = abs(args.units) if args.side == "buy" else -abs(args.units)
        result = submit_oanda_practice_market_order(args.symbol, units=units)
    _print_result(result)


if __name__ == "__main__":
    main()
