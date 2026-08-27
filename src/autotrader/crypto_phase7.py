"""Frozen ADA 5m breakout validation: walk-forward, robustness, and exits."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .crypto_replay import Variant, load_archive, metrics, replay

BASELINE = Variant("BREAKOUT", 15, 60, 30, 0.002)


def _window_stats(v: Variant, bars, windows=5):
    n = len(bars)
    train = max(int(n * 0.25), v.slow * 2)
    test = max(int((n - train) / windows), 1)
    rows = []
    for i in range(windows):
        start = train + i * test
        end = min(start + test, n)
        if end - start < v.slow:
            break
        trades = replay(v, bars, start, end, cost_bps=12, timeframe="5m")
        rows.append(
            {"start": bars[start].timestamp.isoformat(), "end": bars[end - 1].timestamp.isoformat(), **metrics(trades)}
        )
    return rows


def _regimes(trades):
    out = {}
    for name in ("UPTREND", "DOWNTREND", "SIDEWAYS", "HIGH_VOL", "LOW_VOL"):
        out[name] = metrics([t for t in trades if t["entry_regime"] == name])
    return out


def run(path="var/autotrader/crypto_market_data.db", output="var/autotrader/learning/crypto-phase7-validation.json"):
    archives = load_archive(path, "5m", 300)
    baseline = {
        "name": "ADA_5M_BREAKOUT_BASELINE",
        "parameters": BASELINE.__dict__,
        "execution": "signal after close; next bar open entry; 30-bar close time stop; 12bps round trip",
        "symbol": "ADA/USD",
    }
    ada = archives.get("ADA/USD", [])
    n = len(ada)
    a = int(n * 0.6)
    b = int(n * 0.8)
    baseline.update(
        {
            "train": metrics(replay(BASELINE, ada, BASELINE.slow, a, cost_bps=12, timeframe="5m")),
            "validation": metrics(replay(BASELINE, ada, a, b, cost_bps=12, timeframe="5m")),
            "oos": metrics(replay(BASELINE, ada, b, n, cost_bps=12, timeframe="5m")),
            "walk_forward": _window_stats(BASELINE, ada),
        }
    )
    cross = []
    for symbol, bars in archives.items():
        nn = len(bars)
        bb = int(nn * 0.8)
        ts = replay(BASELINE, bars, bb, nn, cost_bps=12, timeframe="5m")
        cross.append({"symbol": symbol, **metrics(ts), "walk_forward": _window_stats(BASELINE, bars)})
    neighbors = (
        [Variant("BREAKOUT", f, s, h, t) for f in (10, 15, 20) for s, h, t in ((60, 30, 0.002),)]
        + [Variant("BREAKOUT", 15, 60, h, 0.002) for h in (20, 40)]
        + [Variant("BREAKOUT", 15, 60, 30, t) for t in (0.0015, 0.0025)]
    )
    stability = []
    for v in neighbors:
        ts = replay(v, ada, b, n, cost_bps=12, timeframe="5m")
        stability.append({"parameters": v.__dict__, **metrics(ts)})
    costs = {}
    for cost in (6, 12, 18, 24, 30):
        costs[str(cost)] = metrics(replay(BASELINE, ada, b, n, cost_bps=cost, timeframe="5m"))
    oos_trades = replay(BASELINE, ada, b, n, cost_bps=12, timeframe="5m")
    regimes = _regimes(oos_trades)
    exits = {}
    for hold in (10, 20, 30, 40, 60):
        v = Variant("BREAKOUT", 15, 60, hold, 0.002)
        exits[f"time_stop_{hold}"] = metrics(replay(v, ada, b, n, cost_bps=12, timeframe="5m"))
    windows = baseline["walk_forward"]
    baseline["walk_forward_summary"] = {
        "windows": len(windows),
        "positive": sum(x["expectancy"] > 0 for x in windows),
        "negative": sum(x["expectancy"] <= 0 for x in windows),
        "survival_rate": sum(x["expectancy"] > 0 for x in windows) / len(windows) if windows else 0,
        "median_expectancy": sorted(x["expectancy"] for x in windows)[len(windows) // 2] if windows else 0,
        "median_pf": sorted((x["profit_factor"] or 0) for x in windows)[len(windows) // 2] if windows else 0,
        "worst_drawdown": max((x["max_drawdown"] for x in windows), default=0),
    }
    positive_cross = sum(x["expectancy"] > 0 for x in cross)
    decision = (
        "EXPERIMENTAL_PAPER"
        if baseline["oos"]["trades"] >= 20
        and baseline["oos"]["expectancy"] > 0
        and (baseline["oos"]["profit_factor"] or 0) > 1
        and baseline["walk_forward_summary"]["positive"] > len(windows) / 2
        and sum(x["expectancy"] > 0 for x in stability) >= len(stability) // 2
        else "NO_EDGE_FOUND"
    )
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": baseline,
        "cross_symbol": {
            "rows": cross,
            "positive": positive_cross,
            "negative": len(cross) - positive_cross,
            "percentage_positive": positive_cross / len(cross) if cross else 0,
            "classification": "GENERAL EDGE"
            if positive_cross / len(cross) > 0.6
            else "PARTIAL GENERALIZATION"
            if positive_cross
            else "ADA-SPECIFIC",
        },
        "parameter_stability": {
            "variants": stability,
            "positive": sum(x["expectancy"] > 0 for x in stability),
            "negative": sum(x["expectancy"] <= 0 for x in stability),
        },
        "cost_stress": costs,
        "regimes": regimes,
        "exit_comparison": exits,
        "decision": decision,
        "registered": False,
        "forward_paper": None,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2) + "\n")
    return result
