from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from .audit import SQLiteAuditStore
from .marketdata import YahooHistoricalData
from .models import AssetClass, AuditEvent, Instrument, MarketBar
from .scanner import CandidateScanner
from .symbols import SymbolNormalizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank market candidates from historical OHLCV")
    parser.add_argument("symbols", nargs="+", help="Symbols to scan")
    parser.add_argument(
        "--asset-class",
        choices=[
            AssetClass.STOCK.value,
            AssetClass.ETF.value,
            AssetClass.CRYPTO.value,
            AssetClass.FOREX.value,
        ],
        default=AssetClass.STOCK.value,
    )
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--audit-db", default="data/audit.db")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    asset_class = AssetClass(args.asset_class)
    normalizer = SymbolNormalizer()
    feed = YahooHistoricalData()
    scanner = CandidateScanner()
    audit = SQLiteAuditStore(args.audit_db)

    end = datetime.now(UTC)
    start = end - timedelta(days=max(args.lookback_days, 1))

    histories: dict[Instrument, list[MarketBar]] = {}
    for raw in args.symbols:
        instrument = normalizer.normalize(raw, asset_class)
        bars = feed.history(instrument, start, end)
        histories[instrument] = bars
        audit.append(
            AuditEvent(
                "market_data_fetch",
                f"Fetched {len(bars)} bars for {instrument.symbol}",
                {"symbol": instrument.symbol, "asset_class": instrument.asset_class.value},
            )
        )

    ranked = scanner.rank(histories, top_n=args.top)
    for index, candidate in enumerate(ranked, start=1):
        volume = "n/a" if candidate.volume_ratio is None else f"{candidate.volume_ratio:.2f}x"
        print(
            f"{index:>2}. {candidate.instrument.symbol:<12} "
            f"score={candidate.score:6.2f} momentum={candidate.momentum_pct:7.2f}% "
            f"range={candidate.average_range_pct:5.2f}% volume={volume} "
            f"stop={candidate.suggested_stop:.4f}"
        )
        audit.append(
            AuditEvent(
                "scan_candidate",
                f"{candidate.instrument.symbol} ranked #{index}",
                {
                    "rank": index,
                    "score": candidate.score,
                    "momentum_pct": candidate.momentum_pct,
                    "average_range_pct": candidate.average_range_pct,
                    "volume_ratio": candidate.volume_ratio,
                    "suggested_stop": candidate.suggested_stop,
                    "reasons": candidate.reasons,
                },
            )
        )


if __name__ == "__main__":
    main()
