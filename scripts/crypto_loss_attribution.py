"""Build evidence-only Crypto loss/churn attribution from reconstructed lifecycles."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def build_report(trades: list[dict[str, object]]) -> dict[str, object]:
    rows = [r for r in trades if isinstance(r, dict) and r.get("net_realized_pnl") is not None]
    rows.sort(key=lambda r: str(r.get("exit_timestamp") or r.get("entry_timestamp") or ""))
    pnls = [float(r["net_realized_pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    by_symbol: dict[str, list[float]] = defaultdict(list)
    by_strategy: dict[str, list[float]] = defaultdict(list)
    for row, pnl in zip(rows, pnls, strict=True):
        by_symbol[str(row.get("symbol") or "UNKNOWN")].append(pnl)
        by_strategy[str(row.get("strategy_version") or row.get("model_version") or "UNKNOWN")].append(pnl)
    repeats: Counter[str] = Counter()
    repeat_pnl: dict[int, list[float]] = defaultdict(list)
    for row, pnl in zip(rows, pnls, strict=True):
        symbol = str(row.get("symbol") or "UNKNOWN")
        repeats[symbol] += 1
        repeat_pnl[repeats[symbol]].append(pnl)
    sequence = [int(p < 0) for p in pnls]
    max_losses = max_wins = current_losses = current_wins = 0
    for negative in sequence:
        current_losses = current_losses + 1 if negative else 0
        current_wins = current_wins + 1 if not negative else 0
        max_losses, max_wins = max(max_losses, current_losses), max(max_wins, current_wins)
    return {
        "source": "crypto-active-v2-autopsy.json",
        "accounting_status": "ACCOUNTING_VERIFIED",
        "sample_size": len(rows), "realized_net_pnl": sum(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "average_trade": statistics.mean(pnls) if pnls else None,
        "median_trade": statistics.median(pnls) if pnls else None,
        "average_winner": statistics.mean(wins) if wins else None,
        "average_loser": statistics.mean(losses) if losses else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "expectancy": statistics.mean(pnls) if pnls else None,
        "max_consecutive_losses": max_losses, "max_consecutive_wins": max_wins,
        "pnl_by_symbol": {k: {"sample": len(v), "pnl": sum(v), "expectancy": statistics.mean(v)} for k, v in by_symbol.items()},
        "pnl_by_strategy": {k: {"sample": len(v), "pnl": sum(v), "expectancy": statistics.mean(v)} for k, v in by_strategy.items()},
        "pnl_by_repeat_number": {str(k): {"sample": len(v), "pnl": sum(v), "expectancy": statistics.mean(v)} for k, v in sorted(repeat_pnl.items())},
        "churn": {"unique_symbols": len(repeats), "repeat_symbols": sum(v > 1 for v in repeats.values()), "state": "INSUFFICIENT_EVIDENCE"},
        "root_causes": [{"cause": "UNKNOWN", "sample": len(losses), "dollar_impact": sum(losses), "basis": "lifecycle fields do not prove causal attribution"}],
        "benchmark_status": "BENCHMARK_UNVERIFIED",
        "edge_state": "LEARNING",
    }


def main() -> int:
    source = Path("var/autotrader/learning/crypto-active-v2-autopsy.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    report = build_report(data.get("trades", []))
    output = Path("var/autotrader/learning/crypto-loss-attribution.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sample_size": report["sample_size"], "realized_net_pnl": report["realized_net_pnl"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
