from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autotrader.audit import SQLiteAuditStore
from autotrader.coordinated_dry_run import DryRunCandidate, FivePillarDryRunner
from autotrader.coordinated_test import FivePillarTestConfig
from autotrader.marketdata import YahooHistoricalData
from autotrader.models import AssetClass, Instrument, Side, TradeProposal
from autotrader.scanner import CandidateScanner

DRY_RUN_UNIVERSE = (
    ("alpaca_equities", "alpaca-paper", Instrument("SPY", AssetClass.ETF)),
    ("oanda_fx", "oanda-practice", Instrument("EUR/USD", AssetClass.FOREX)),
    ("alpaca_crypto", "alpaca-crypto-paper", Instrument("BTC/USD", AssetClass.CRYPTO)),
    ("alpaca_metals", "alpaca-metals-paper", Instrument("GLD", AssetClass.ETF)),
)


def live_candidates(now: datetime) -> tuple[list[DryRunCandidate], dict[str, str]]:
    feed = YahooHistoricalData()
    scanner = CandidateScanner()
    candidates = []
    coverage = {name: "no usable market data" for name, _, _ in DRY_RUN_UNIVERSE}
    coverage["ibkr_global"] = "Saxo market candidate selection not configured; connectivity only"
    for pillar, broker, instrument in DRY_RUN_UNIVERSE:
        try:
            bars = feed.history(instrument, now - timedelta(days=45), now, interval="1d")
            scored = scanner.score_instrument(instrument, bars)
        except Exception as exc:
            coverage[pillar] = f"market read failed: {type(exc).__name__}"
            continue
        if scored is None:
            continue
        side = Side.BUY if scored.momentum_pct >= 0 else Side.SELL
        stop = scored.suggested_stop
        risk = abs(scored.last_price - stop)
        target = scored.last_price + risk * 1.5 if side is Side.BUY else scored.last_price - risk * 1.5
        confidence = min(0.95, 0.50 + scored.score / 200.0)
        candidates.append(
            DryRunCandidate(
                pillar=pillar,
                broker=broker,
                proposal=TradeProposal(
                    instrument.symbol,
                    instrument.asset_class,
                    side,
                    scored.last_price,
                    stop,
                    confidence,
                    "five-pillar-dry-run-scanner",
                ),
                order_type="market+protective-stop",
                target_price=target,
                strategy_version="baseline-scanner-v1",
                reason=(
                    f"scanner score {scored.score:.2f}; momentum {scored.momentum_pct:.2f}%; "
                    + (", ".join(scored.reasons) or "baseline eligibility")
                ),
            )
        )
        coverage[pillar] = "candidate evaluated"
    return candidates, coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="No-submit coordinated five-pillar dry run")
    parser.add_argument("--output", default="var/autotrader/five_pillar_dry_run.json")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    args = parser.parse_args()
    now = datetime.now(UTC)
    candidates, coverage = live_candidates(now)
    decisions = FivePillarDryRunner(SQLiteAuditStore(args.audit_db)).run(candidates, now=now)
    payload = {
        "generated_at": now.isoformat(),
        "dry_run": True,
        "orders_submitted": 0,
        "configuration": FivePillarTestConfig().as_dict(),
        "coverage": coverage,
        "manifest": [asdict(item) for item in decisions],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
