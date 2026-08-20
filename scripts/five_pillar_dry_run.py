from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autotrader.audit import SQLiteAuditStore
from autotrader.brokers.safety import alpaca_open_positions, oanda_open_positions
from autotrader.brokers.saxo_sim import SaxoInstrumentSummary, SaxoSimAdapter
from autotrader.capital_allocations import TOTAL_PAPER_CAPITAL
from autotrader.coordinated_dry_run import DryRunCandidate, FivePillarDryRunner
from autotrader.coordinated_test import FivePillarTestConfig
from autotrader.execution_preview import preview_execution_pipeline
from autotrader.marketdata import YahooHistoricalData
from autotrader.models import AssetClass, Instrument, PortfolioState, Position, Side, TradeProposal
from autotrader.open_risk import portfolio_open_risk
from autotrader.portfolio_ledger import PortfolioLedger
from autotrader.scanner import CandidateScanner

DRY_RUN_UNIVERSE = (
    ("alpaca_equities", "alpaca-paper", Instrument("SPY", AssetClass.ETF)),
    ("oanda_fx", "oanda-practice", Instrument("EUR/USD", AssetClass.FOREX)),
    ("alpaca_crypto", "alpaca-crypto-paper", Instrument("BTC/USD", AssetClass.CRYPTO)),
    ("alpaca_metals", "alpaca-metals-paper", Instrument("GLD", AssetClass.ETF)),
)
SAXO_DISCOVERY_SPECS = (
    ("ASML", "ASML HOLDING"),
    ("Novo Nordisk", "NOVO NORDISK"),
    ("SAP SE", "SAP SE"),
    ("Toyota Motor", "TOYOTA MOTOR"),
    ("Nestle SA", "NESTLE SA"),
)
US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE_ARCA", "AMEX", "BATS", "OTCBB", "OTC_GREY"}


def live_candidates(
    now: datetime,
) -> tuple[list[DryRunCandidate], dict[str, str], dict[str, object]]:
    feed = YahooHistoricalData()
    scanner = CandidateScanner()
    candidates = []
    coverage = {name: "no usable market data" for name, _, _ in DRY_RUN_UNIVERSE}
    coverage["ibkr_global"] = "Saxo SIM discovery pending"
    discovery: dict[str, object] = {"environment": "sim", "eligible_instruments": [], "status": "pending"}
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
                market_data_timestamp=bars[-1].timestamp.isoformat(),
            )
        )
        coverage[pillar] = "candidate evaluated"

    international, discovery = saxo_international_candidate()
    if international is not None:
        candidates.append(international)
        coverage["ibkr_global"] = "Saxo SIM international candidate evaluated"
    else:
        coverage["ibkr_global"] = str(discovery.get("status") or "no qualifying international candidate")
    return candidates, coverage, discovery


def saxo_international_candidate() -> tuple[DryRunCandidate | None, dict[str, object]]:
    """Discover and score non-US Saxo SIM listings using GET-only reference/chart data."""

    discovery: dict[str, object] = {"environment": "sim", "eligible_instruments": [], "status": "pending"}
    try:
        adapter = SaxoSimAdapter.from_env()
        instruments: dict[tuple[int, str], SaxoInstrumentSummary] = {}
        for term, expected_name in SAXO_DISCOVERY_SPECS:
            for instrument in adapter.search_instruments(term, top=10):
                exchange = (instrument.exchange_id or "").upper()
                description = instrument.description.upper()
                is_expected_company = expected_name in description
                is_restricted_or_adr = "REDUCE ONLY" in description or "ADR" in description
                if exchange and exchange not in US_EXCHANGES and is_expected_company and not is_restricted_or_adr:
                    instruments[(instrument.uic, instrument.asset_type)] = instrument
    except Exception as exc:
        discovery["status"] = f"Saxo SIM discovery failed: {type(exc).__name__}"
        return None, discovery

    eligible = sorted(instruments.values(), key=lambda item: (item.exchange_id or "", item.symbol))
    discovery["eligible_instruments"] = [
        {
            "uic": item.uic,
            "asset_type": item.asset_type,
            "symbol": item.symbol,
            "description": item.description,
            "exchange_id": item.exchange_id,
        }
        for item in eligible
    ]
    scanner = CandidateScanner()
    scored_rows = []
    for item in eligible:
        try:
            samples = adapter.chart_samples(item, horizon_minutes=1440, count=45)
            bars = [
                _saxo_market_bar(item, sample)
                for sample in samples
            ]
            scored = scanner.score_instrument(Instrument(item.symbol, AssetClass.STOCK), bars)
        except Exception:
            continue
        if scored is not None:
            scored_rows.append((scored.score, item, scored, bars[-1].timestamp))
    if not scored_rows:
        discovery["status"] = f"discovered {len(eligible)} eligible listings; no qualifying chart candidate"
        return None, discovery

    _, item, scored, timestamp = max(scored_rows, key=lambda row: row[0])
    side = Side.BUY if scored.momentum_pct >= 0 else Side.SELL
    risk = abs(scored.last_price - scored.suggested_stop)
    target = scored.last_price + risk * 1.5 if side is Side.BUY else scored.last_price - risk * 1.5
    discovery["status"] = f"discovered {len(eligible)} eligible listings; selected {item.symbol}"
    discovery["selected"] = {
        "uic": item.uic,
        "asset_type": item.asset_type,
        "symbol": item.symbol,
        "exchange_id": item.exchange_id,
    }
    return (
        DryRunCandidate(
            pillar="ibkr_global",
            broker="saxo-sim",
            proposal=TradeProposal(
                item.symbol,
                AssetClass.STOCK,
                side,
                scored.last_price,
                scored.suggested_stop,
                min(0.95, 0.50 + scored.score / 200.0),
                "five-pillar-saxo-sim-scanner",
            ),
            order_type="market+protective-stop",
            target_price=target,
            strategy_version="baseline-saxo-scanner-v1",
            reason=(
                f"scanner score {scored.score:.2f}; momentum {scored.momentum_pct:.2f}%; "
                + (", ".join(scored.reasons) or "baseline eligibility")
            ),
            market_data_timestamp=timestamp.isoformat(),
            broker_metadata={
                "uic": item.uic,
                "asset_type": item.asset_type,
                "exchange_id": item.exchange_id,
                "description": item.description,
            },
        ),
        discovery,
    )


def _saxo_market_bar(item, sample):
    from autotrader.models import MarketBar

    timestamp = datetime.fromisoformat(sample.timestamp.replace("Z", "+00:00"))
    return MarketBar(
        symbol=item.symbol,
        asset_class=AssetClass.STOCK,
        timestamp=timestamp,
        open=sample.open,
        high=sample.high,
        low=sample.low,
        close=sample.close,
        volume=sample.volume,
    )


def current_internal_exposure() -> tuple[
    PortfolioState,
    dict[str, float],
    dict[str, float],
    dict[str, object],
]:
    """Map current paper positions onto internal capital without using broker balances."""

    stop_map: dict[str, float] = {}
    try:
        loaded = PortfolioLedger("var/autotrader/portfolio.db").load_portfolio()
        if loaded is not None:
            stop_map = {symbol: position.stop_price for symbol, position in loaded[0].positions.items()}
    except Exception:
        pass

    positions: dict[str, Position] = {}
    marks: dict[str, float] = {}
    deployed = {pillar: 0.0 for pillar, _, _ in DRY_RUN_UNIVERSE}
    deployed["ibkr_global"] = 0.0
    warnings = []
    try:
        rows = alpaca_open_positions().details.get("positions", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            raw_symbol = str(row.get("symbol") or "").upper()
            is_crypto = str(row.get("asset_class") or "").lower() == "crypto"
            symbol = "BTC/USD" if raw_symbol == "BTCUSD" else raw_symbol
            pillar = "alpaca_crypto" if is_crypto else ("alpaca_metals" if symbol == "GLD" else "alpaca_equities")
            asset_class = AssetClass.CRYPTO if is_crypto else AssetClass.STOCK
            quantity = abs(float(row.get("qty") or 0.0))
            average = float(row.get("avg_entry_price") or 0.0)
            mark = float(row.get("current_price") or average)
            notional = abs(float(row.get("market_value") or quantity * mark))
            if quantity <= 0 or average <= 0:
                continue
            stop = stop_map.get(symbol, max(average * 0.0001, 1e-8))
            if symbol not in stop_map:
                warnings.append(f"{symbol}: no internal stop found; exposure treated conservatively")
            positions[symbol] = Position(symbol, asset_class, quantity, average, stop)
            marks[symbol] = mark
            deployed[pillar] += notional
    except Exception as exc:
        warnings.append(f"Alpaca position read failed: {type(exc).__name__}")

    try:
        rows = oanda_open_positions().details.get("positions", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("instrument") or "").replace("_", "/").upper()
            long = row.get("long") if isinstance(row.get("long"), dict) else {}
            short = row.get("short") if isinstance(row.get("short"), dict) else {}
            units = float(long.get("units") or 0.0) + float(short.get("units") or 0.0)
            side = long if units >= 0 else short
            quantity = abs(units)
            average = float(side.get("averagePrice") or 0.0)
            if quantity <= 0 or average <= 0:
                continue
            stop = stop_map.get(symbol, max(average * 0.0001, 1e-8))
            if symbol not in stop_map:
                warnings.append(f"{symbol}: no internal stop found; exposure treated conservatively")
            positions[symbol] = Position(symbol, AssetClass.FOREX, quantity, average, stop)
            marks[symbol] = average
            deployed["oanda_fx"] += quantity * average
    except Exception as exc:
        warnings.append(f"OANDA position read failed: {type(exc).__name__}")

    total_deployed = sum(deployed.values())
    state = PortfolioState(
        equity=TOTAL_PAPER_CAPITAL,
        cash=max(TOTAL_PAPER_CAPITAL - total_deployed, 0.0),
        positions=positions,
    )
    return state, deployed, marks, {
        "verified": not any("read failed" in warning for warning in warnings),
        "deployed_by_pillar": deployed,
        "total_deployed": total_deployed,
        "open_positions": sorted(positions),
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="No-submit coordinated five-pillar dry run")
    parser.add_argument("--output", default="var/autotrader/five_pillar_dry_run.json")
    parser.add_argument("--audit-db", default="var/autotrader/audit.db")
    args = parser.parse_args()
    now = datetime.now(UTC)
    candidates, coverage, discovery = live_candidates(now)
    portfolio, deployed, marks, exposure = current_internal_exposure()
    existing_risk = portfolio_open_risk(portfolio, mark_prices=marks).total_open_risk_dollars
    audit = SQLiteAuditStore(args.audit_db)
    decisions = FivePillarDryRunner(audit).run(
        candidates,
        portfolio=portfolio,
        deployed_by_pillar=deployed,
        mark_prices=marks,
        now=now,
    )
    proposed_deployed = sum(item.notional_exposure for item in decisions if item.risk_engine_status == "approved")
    proposed_risk = sum(item.dollars_at_risk for item in decisions if item.risk_engine_status == "approved")
    protected_cash = TOTAL_PAPER_CAPITAL * 0.10
    total_deployed = float(exposure["total_deployed"]) + proposed_deployed
    pipeline_preview = preview_execution_pipeline(decisions, audit=audit, now=now)
    payload = {
        "generated_at": now.isoformat(),
        "dry_run": True,
        "orders_submitted": 0,
        "configuration": FivePillarTestConfig().as_dict(),
        "coverage": coverage,
        "saxo_discovery": discovery,
        "existing_internal_exposure": exposure,
        "portfolio_preview": {
            "starting_strategy_capital": TOTAL_PAPER_CAPITAL,
            "existing_deployed_capital": exposure["total_deployed"],
            "proposed_deployed_capital": proposed_deployed,
            "total_deployed_capital": total_deployed,
            "remaining_available_cash": max(TOTAL_PAPER_CAPITAL - total_deployed - protected_cash, 0.0),
            "protected_cash": protected_cash,
            "existing_dollars_at_risk": existing_risk,
            "proposed_dollars_at_risk": proposed_risk,
            "total_dollars_at_risk": existing_risk + proposed_risk,
            "portfolio_risk_pct": (existing_risk + proposed_risk) / TOTAL_PAPER_CAPITAL,
            "proposed_deployment_by_pillar": {
                pillar: sum(
                    item.notional_exposure
                    for item in decisions
                    if item.pillar == pillar and item.risk_engine_status == "approved"
                )
                for pillar in deployed
            },
        },
        "execution_pipeline_preview": pipeline_preview,
        "manifest": [asdict(item) for item in decisions],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
