"""Read-only forward shadow state for the frozen ADA 5m candidate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .crypto_replay import Variant, load_archive, metrics, replay

BASELINE = Variant("BREAKOUT", 15, 60, 30, 0.002)
STATES = ("NO_SIGNAL", "SHADOW_SIGNAL", "SHADOW_OPEN", "SHADOW_CLOSED")


def update_shadow(
    db_path="var/autotrader/crypto_market_data.db", output="var/autotrader/learning/crypto-shadow-forward.json"
):
    bars = load_archive(db_path, "5m", 300).get("ADA/USD", [])
    prior = {}
    path = Path(output)
    if path.exists():
        try:
            prior = json.loads(path.read_text())
        except (OSError, ValueError):
            prior = {}
    last = prior.get("last_timestamp")
    start = next((i for i, b in enumerate(bars) if not last or b.timestamp.isoformat() > last), BASELINE.slow)
    signals = replay(BASELINE, bars, max(start, BASELINE.slow), len(bars), cost_bps=12, timeframe="5m")
    existing = prior.get("trades") if isinstance(prior.get("trades"), list) else []
    known = {x.get("signal_timestamp") for x in existing if isinstance(x, dict)}
    new = [x for x in signals if x["signal_timestamp"] not in known]
    trades = [*existing, *new]
    summary = metrics(trades)
    payload = {
        "candidate": "ADA_5M_BREAKOUT_BASELINE",
        "state": "SHADOW",
        "last_timestamp": bars[-1].timestamp.isoformat() if bars else last,
        "signals": len(trades),
        "completed_shadow_trades": len(trades),
        "open": 0,
        "shadow_pnl": summary["net_pnl"],
        "metrics": summary,
        "trades": trades,
        "broker_submission": False,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
