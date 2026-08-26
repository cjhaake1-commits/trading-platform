"""Deterministic, leakage-safe Crypto bar replay and bounded tournament."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import pstdev

FAMILIES = (
    "MOMENTUM",
    "BREAKOUT",
    "TREND",
    "MEAN_REVERSION",
    "VOLATILITY_EXPANSION",
    "SHORT_HORIZON_REVERSAL",
    "RELATIVE_STRENGTH",
    "BTC_REGIME_CONDITIONED",
    "MULTI_TIMEFRAME_TREND",
    "VOLUME_CONFIRMED",
)


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Variant:
    family: str
    fast: int
    slow: int
    hold: int
    threshold: float

    @property
    def id(self) -> str:
        return f"{self.family.lower()}__f{self.fast}_s{self.slow}_h{self.hold}_t{self.threshold:g}"


def load_archive(path: str | Path, timeframe: str = "1m", min_bars: int = 300) -> dict[str, list[Bar]]:
    with sqlite3.connect(path) as con:
        rows = con.execute(
            "SELECT symbol,timestamp,open,high,low,close,volume FROM bars WHERE timeframe=? ORDER BY symbol,timestamp",
            (timeframe,),
        ).fetchall()
    result: dict[str, list[Bar]] = {}
    for symbol, stamp, op, hi, lo, close, volume in rows:
        b = Bar(
            symbol,
            datetime.fromisoformat(stamp).astimezone(UTC),
            float(op),
            float(hi),
            float(lo),
            float(close),
            float(volume),
        )
        if (
            b.high < max(b.open, b.close, b.low)
            or b.low > min(b.open, b.close, b.high)
            or b.volume < 0
            or not all(math.isfinite(x) and x > 0 for x in (b.open, b.high, b.low, b.close))
        ):
            continue
        result.setdefault(symbol, []).append(b)
    return {s: bars for s, bars in result.items() if len(bars) >= min_bars}


def variants() -> list[Variant]:
    return [Variant(f, 5, 20, 10, 0.001) for f in FAMILIES] + [Variant(f, 15, 60, 30, 0.002) for f in FAMILIES]


def regime(bars: list[Bar], i: int, window: int = 60) -> str:
    if i < window:
        return "INSUFFICIENT"
    closes = [b.close for b in bars[i - window : i + 1]]
    returns = [closes[j] / closes[j - 1] - 1 for j in range(1, len(closes))]
    avg = sum(returns) / len(returns) if returns else 0.0
    vol = math.sqrt(sum((x - avg) ** 2 for x in returns) / len(returns)) if returns else 0.0
    slope = (closes[-1] - closes[0]) / closes[0]
    if vol > 0.004:
        return "HIGH_VOL"
    if vol < 0.0007:
        return "LOW_VOL"
    if slope > 0.01:
        return "UPTREND"
    if slope < -0.01:
        return "DOWNTREND"
    return "SIDEWAYS"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def signal(v: Variant, bars: list[Bar], i: int, btc: list[Bar] | None = None, closes: list[float] | None = None) -> int:
    if i < v.slow:
        return 0
    c = closes or [b.close for b in bars]
    fast = _mean(c[i - v.fast : i])
    slow = _mean(c[i - v.slow : i])
    prev = c[i - 1]
    ret = prev / c[i - v.fast] - 1
    vol = _mean([b.volume for b in bars[i - v.fast : i]])
    if v.family in {"MOMENTUM", "TREND"}:
        return 1 if fast > slow and ret > v.threshold else 0
    if v.family == "BREAKOUT":
        return 1 if prev > max(c[i - v.slow : i - 1]) * (1 + v.threshold) else 0
    if v.family == "MEAN_REVERSION":
        return 1 if prev < slow * (1 - v.threshold * 2) else 0
    if v.family == "VOLATILITY_EXPANSION":
        ranges = [(b.high - b.low) / b.close for b in bars[i - v.slow : i]]
        return 1 if ranges[-1] > _mean(ranges[:-1]) * 1.5 and prev > slow else 0
    if v.family == "SHORT_HORIZON_REVERSAL":
        return 1 if ret < -v.threshold * 2 and prev > bars[i - 1].low else 0
    if v.family == "VOLUME_CONFIRMED":
        return 1 if fast > slow and bars[i - 1].volume > vol * 1.5 else 0
    if v.family == "BTC_REGIME_CONDITIONED":
        return (
            1
            if btc and i < len(btc) and btc[i].close > _mean([b.close for b in btc[i - v.slow : i]]) and fast > slow
            else 0
        )
    if v.family == "MULTI_TIMEFRAME_TREND":
        return 1 if fast > slow and regime(bars, i) == "UPTREND" else 0
    if v.family == "RELATIVE_STRENGTH":
        return 1 if ret > v.threshold else 0
    return 0


def metrics(trades: list[dict[str, object]], capital: float = 1000.0) -> dict[str, object]:
    vals = [float(t["net_pnl"]) for t in trades]
    wins = [x for x in vals if x > 0]
    losses = [x for x in vals if x < 0]
    curve = peak = dd = 0.0
    for x in vals:
        curve += x
        peak = max(peak, curve)
        dd = max(dd, peak - curve)
    hours = sum(float(t["holding_minutes"]) / 60 for t in trades)
    return {
        "trades": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(vals) if vals else 0.0,
        "average_win": _mean(wins),
        "average_loss": _mean(losses),
        "payoff_ratio": _mean(wins) / abs(_mean(losses)) if wins and losses else None,
        "expectancy": _mean(vals),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "gross_pnl": sum(float(t["gross_pnl"]) for t in trades),
        "net_pnl": sum(vals),
        "max_drawdown": dd,
        "return": sum(vals) / capital,
        "volatility": pstdev(vals) if len(vals) > 1 else 0.0,
        "risk_adjusted_return": (_mean(vals) / pstdev(vals)) if len(vals) > 1 and pstdev(vals) else 0.0,
        "capital_turns": sum(float(t["capital_used"]) for t in trades) / capital,
        "capital_hours": hours,
        "pnl_per_capital_hour": sum(vals) / hours if hours else 0.0,
        "average_holding_minutes": _mean([float(t["holding_minutes"]) for t in trades]),
    }


def replay(
    v: Variant,
    bars: list[Bar],
    start: int,
    end: int,
    btc: list[Bar] | None = None,
    capital: float = 1000.0,
    cost_bps: float = 12.0,
) -> list[dict[str, object]]:
    trades = []
    i = max(start, v.slow)
    end = min(end, len(bars) - 1)
    closes = [b.close for b in bars]
    while i < end - 1:
        if signal(v, bars, i, btc, closes) == 0:
            i += 1
            continue
        entry = bars[i + 1]
        exit_i = min(i + 1 + v.hold, end)
        exit_bar = bars[exit_i]
        entry_price = entry.open * (1 + cost_bps / 20000)
        exit_price = exit_bar.close * (1 - cost_bps / 20000)
        gross = (exit_price - entry_price) / entry_price * capital
        cost = capital * cost_bps / 10000
        net = gross - cost
        path = bars[i + 1 : exit_i + 1]
        mfe = max((b.high - entry_price) / entry_price * capital for b in path)
        mae = min((b.low - entry_price) / entry_price * capital for b in path)
        trades.append(
            {
                "strategy_id": v.id,
                "family": v.family,
                "parameter_set": asdict(v),
                "symbol": bars[0].symbol,
                "timeframe": "1m",
                "signal_timestamp": bars[i].timestamp.isoformat(),
                "entry_timestamp": entry.timestamp.isoformat(),
                "entry_price": entry_price,
                "exit_timestamp": exit_bar.timestamp.isoformat(),
                "exit_price": exit_price,
                "quantity": capital / entry_price,
                "capital_used": capital,
                "holding_minutes": (exit_bar.timestamp - entry.timestamp).total_seconds() / 60,
                "gross_pnl": gross,
                "estimated_cost": cost,
                "slippage": cost,
                "net_pnl": net,
                "MFE": mfe,
                "MAE": mae,
                "entry_regime": regime(bars, i),
                "exit_reason": "TIME_STOP",
            }
        )
        i = exit_i + 1
    return trades


def run_tournament(
    path: str | Path = "var/autotrader/crypto_market_data.db",
    output: str | Path = "var/autotrader/learning/crypto-replay-tournament.json",
) -> dict[str, object]:
    all_archives = load_archive(path)
    # Bounded first tournament: use the 12 most-covered executable pairs.
    ordered = sorted(all_archives, key=lambda s: len(all_archives[s]), reverse=True)[:2]
    archives = {s: all_archives[s] for s in ordered}
    results = []
    ledger = []
    for v in variants():
        for symbol, bars in archives.items():
            n = len(bars)
            a = int(n * 0.6)
            b = int(n * 0.8)
            btc = archives.get("BTC/USD")
            parts = []
            for label, x, y in (("TRAIN", v.slow, a), ("VALIDATION", a, b), ("OOS", b, n)):
                ts = replay(v, bars, x, y, btc)
                ledger.extend(ts)
                parts.append((label, metrics(ts)))
            results.append(
                {
                    "strategy_id": v.id,
                    "symbol": symbol,
                    "family": v.family,
                    "parameters": asdict(v),
                    "partitions": dict(parts),
                }
            )
    ranked = sorted(results, key=lambda x: x["partitions"]["VALIDATION"]["expectancy"], reverse=True)
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": "crypto_replay_v1",
        "execution": "signal after bar close; entry next bar open; exit close after bounded holding period; 12bps round-trip cost/slippage",
        "eligible_symbols": ordered,
        "eligible_timeframes": ["1m"],
        "bar_count": sum(map(len, archives.values())),
        "strategy_variants": len(variants()),
        "total_strategies_tested": len(results),
        "total_simulated_trades": len(ledger),
        "ranked": ranked,
        "top_five": ranked[:5],
        "trade_ledger": ledger,
        "promotion_state": "NO_EDGE_FOUND",
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8")
    return artifact
