from __future__ import annotations

import argparse

from .brokers.paper import PaperBroker
from .models import AssetClass, PortfolioState, Side, TradeProposal
from .risk import RiskEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper-trading bootstrap runner")
    parser.add_argument("--symbol", default="NVDA")
    parser.add_argument("--price", type=float, required=True)
    parser.add_argument("--stop", type=float)
    parser.add_argument("--equity", type=float, default=1000.0)
    parser.add_argument("--asset-class", choices=[a.value for a in AssetClass], default="stock")
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    stop = args.stop if args.stop is not None else args.price * 0.98

    portfolio = PortfolioState(equity=args.equity, cash=args.equity)
    proposal = TradeProposal(
        symbol=args.symbol.upper(),
        asset_class=AssetClass(args.asset_class),
        side=Side.BUY,
        entry_price=args.price,
        stop_price=stop,
        confidence=0.50,
        source="bootstrap-cli",
        rationale="Manual bootstrap proposal for validating the risk/execution pipeline.",
    )

    engine = RiskEngine()
    decision = engine.evaluate(proposal, portfolio)

    print(f"proposal={proposal}")
    print(f"risk_decision={decision}")

    if decision.approved and not args.dry_run:
        broker = PaperBroker(portfolio)
        fill = broker.execute(proposal, decision)
        print(f"paper_fill={fill}")
        print(f"cash_remaining={portfolio.cash:.2f}")


if __name__ == "__main__":
    main()
