"""Generate a read-only ACTIVE-V2 Crypto autopsy from Alpaca PAPER history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from autotrader.brokers.safety import _alpaca_auth, _alpaca_headers, _request
from autotrader.crypto_autopsy import build_learning_registry, reconstruct_lifecycles, summarize


def main() -> int:
    key, secret, base = _alpaca_auth()
    payload, _headers = _request(
        f"{base.rstrip('/')}/v2/orders?status=all&limit=500&direction=desc",
        method="GET",
        headers=_alpaca_headers(key, secret),
    )
    orders = payload if isinstance(payload, list) else []
    manifests: dict[str, dict[str, object]] = {}
    with sqlite3.connect("var/autotrader/portfolio.db") as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM entry_manifests WHERE broker_order_id IS NOT NULL"):
            manifests[str(row["broker_order_id"])] = dict(row)
    trades = reconstruct_lifecycles(orders, manifests)
    summary = summarize(trades)
    registry = build_learning_registry(summary)
    output = Path("var/autotrader/learning/crypto-active-v2-autopsy.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"registry": registry, "trades": trades}, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"output": str(output), "trades": len(trades), "realized_pnl": summary["realized_pnl"], "win_rate": summary["win_rate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
