"""Place one deliberately tiny OANDA practice trade and verify it.

This script is intentionally NOT autonomous. It requires explicit opt-in via
OANDA_ALLOW_PAPER_ORDER=YES and will only use the OANDA practice endpoint.
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.oanda_practice import OandaPracticeClient


def main() -> None:
    if os.getenv("OANDA_ALLOW_PAPER_ORDER") != "YES":
        raise RuntimeError(
            "Paper-order gate is closed. Set OANDA_ALLOW_PAPER_ORDER=YES for this run only."
        )

    client = OandaPracticeClient()
    instrument = os.getenv("OANDA_TEST_INSTRUMENT", "EUR_USD")

    open_before = client.open_trades().get("trades", [])
    if len(open_before) >= 3:
        raise RuntimeError("Risk gate: maximum 3 open trades already reached.")

    pricing = client.price(instrument)
    prices = pricing.get("prices", [])
    if not prices or not prices[0].get("asks"):
        raise RuntimeError(f"No tradable ask price returned for {instrument}.")

    ask = Decimal(prices[0]["asks"][0]["price"])

    # Deliberately tiny integration trade: 1 unit. The stop is 0.50% below
    # the observed ask, keeping this far below the platform's 0.5%-equity cap.
    units = 1
    stop = (ask * Decimal("0.995")).quantize(Decimal("0.00001"))
    if stop >= ask:
        raise RuntimeError("Invalid stop calculation.")

    order = client.market_order(instrument, units, str(stop))
    fill = order.get("orderFillTransaction")
    if not fill:
        raise RuntimeError(f"Order was not filled: {json.dumps(order, indent=2)}")

    open_after = client.open_trades().get("trades", [])
    trade_id = fill.get("tradeOpened", {}).get("tradeID")
    verified = bool(trade_id) and any(str(t.get("id")) == str(trade_id) for t in open_after)

    audit = {
        "environment": "practice",
        "instrument": instrument,
        "units": units,
        "observed_ask": str(ask),
        "stop_loss": str(stop),
        "order_id": fill.get("orderID"),
        "trade_id": trade_id,
        "fill_price": fill.get("price"),
        "verified_open_trade": verified,
        "open_trade_count_after": len(open_after),
    }
    print(json.dumps(audit, indent=2))

    if not verified:
        raise RuntimeError("Broker returned a fill, but the opened trade could not be verified.")


if __name__ == "__main__":
    main()
