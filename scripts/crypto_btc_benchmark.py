"""Attach point-in-time BTC/USD interval benchmarks to verified Crypto trades."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from autotrader.brokers.safety import _alpaca_auth, _alpaca_headers


def _parse(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _price(base: str, headers: dict[str, str], when: datetime) -> tuple[float | None, str | None]:
    params = urlencode({"symbols": "BTC/USD", "timeframe": "1Min", "start": (when - timedelta(minutes=3)).isoformat(), "end": (when + timedelta(minutes=3)).isoformat(), "limit": "20"})
    try:
        with urlopen(Request(f"https://data.alpaca.markets/v1beta3/crypto/us/bars?{params}", headers=headers), timeout=10) as response:
            payload = json.load(response)
        bars = payload.get("bars", {}).get("BTC/USD", []) if isinstance(payload, dict) else []
        candidates = [(abs((_parse(row.get("t")) - when).total_seconds()), float(row["c"]), _parse(row.get("t"))) for row in bars if _parse(row.get("t")) and row.get("c") is not None]
        if not candidates:
            return None, None
        _, price, timestamp = min(candidates, key=lambda item: item[0])
        return price, timestamp.isoformat() if timestamp else None
    except Exception:
        return None, None


def main() -> int:
    source = Path("var/autotrader/learning/crypto-active-v2-autopsy.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    key, secret, _ = _alpaca_auth()
    headers = _alpaca_headers(key, secret)
    rows = []
    for trade in data.get("trades", []):
        entry = _parse(trade.get("entry_timestamp"))
        exit_ = _parse(trade.get("exit_timestamp"))
        base = {"lifecycle_id": trade.get("trade_id"), "benchmark_symbol": "BTC/USD", "source": "Alpaca historical Crypto bars", "benchmark_status": "BENCHMARK_UNVERIFIED"}
        if not entry or not exit_ or not key or not secret:
            rows.append(base)
            continue
        ep, et = _price("https://data.alpaca.markets", headers, entry)
        xp, xt = _price("https://data.alpaca.markets", headers, exit_)
        capital = float(trade.get("gross_entry_value") or 0.0)
        strategy = float(trade.get("net_realized_pnl") or 0.0) / capital if capital else None
        benchmark = xp / ep - 1.0 if ep and xp else None
        base.update({"entry_benchmark_timestamp": et, "exit_benchmark_timestamp": xt, "entry_benchmark_price": ep, "exit_benchmark_price": xp, "strategy_return": strategy, "benchmark_return": benchmark, "excess_return": strategy - benchmark if strategy is not None and benchmark is not None else None, "benchmark_status": "VERIFIED" if strategy is not None and benchmark is not None else "BENCHMARK_UNVERIFIED"})
        rows.append(base)
    out = Path("var/autotrader/learning/crypto-btc-benchmark.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "rows": rows, "coverage": sum(r["benchmark_status"] == "VERIFIED" for r in rows) / len(rows) if rows else 0.0}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "rows": len(rows), "verified": sum(r["benchmark_status"] == "VERIFIED" for r in rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
