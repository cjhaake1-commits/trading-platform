from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .brokers.alpaca_metals_paper import AlpacaMetalsConfigurationError
from .brokers.saxo_sim import SaxoSimAdapter
from .capital_allocations import PILLAR_METALS
from .international_trading import InternationalExecutionService
from .marketdata import YahooHistoricalData
from .metals_trading import MetalsExecutionService
from .models import AssetClass, Instrument, MarketBar, Side
from .runtime import JobResult
from .scanner import CandidateScanner
from .strategies import BaselineStrategies


def _bars_from_saxo(samples, instrument: Instrument) -> list[MarketBar]:
    bars: list[MarketBar] = []
    for sample in samples:
        try:
            timestamp = datetime.fromisoformat(sample.timestamp.replace("Z", "+00:00"))
            bars.append(
                MarketBar(
                    symbol=instrument.symbol,
                    asset_class=instrument.asset_class,
                    timestamp=timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC),
                    open=float(sample.open),
                    high=float(sample.high),
                    low=float(sample.low),
                    close=float(sample.close),
                    volume=float(sample.volume),
                )
            )
        except Exception:
            continue
    return bars


def _write_saxo_permission_status(*, now: datetime, authenticated: bool, read_only: bool | None, error: str | None = None, shadow_candidate: str | None = None, precheck: dict[str, object] | None = None, capabilities: dict[str, object] | None = None, session_capabilities: dict[str, object] | None = None) -> None:
    path = Path("var/autotrader/saxo-permission.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "authenticated": authenticated,
        "environment": "sim",
        "base_url": "https://gateway.saxobank.com/sim/openapi",
        "read_only": read_only,
        "write_permission": authenticated and read_only is False,
        "write_capability": "WRITABLE" if read_only is False else ("READ_ONLY" if read_only is True else "UNKNOWN"),
        "execution_state": "READY / EVALUATING" if authenticated and read_only is False else ("EXTERNAL ACCOUNT WRITE BLOCK" if authenticated else "AUTH REQUIRED"),
        "last_permission_check": now.astimezone(UTC).isoformat(),
        "shadow_candidate": shadow_candidate,
        "shadow_rejection": "EXTERNAL_ACCOUNT_WRITE_PERMISSION" if read_only is not False else None,
        "error": error,
        "precheck": precheck or {"state": "NOT_RUN"},
        "capabilities": capabilities or {"write_scope_present": None},
        "session_capabilities": session_capabilities or {"state": "NOT_RUN"},
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


@dataclass
class MetalsPaperTradingJob:
    name: str = "alpaca-metals-paper-trading"
    cadence_seconds: float = 300.0
    history_path: str = "var/autotrader/metals_trades.db"
    universe: tuple[str, ...] = ("GLD", "IAU", "SGOL", "SLV", "SIVR", "GDX", "GDXJ", "SIL")

    def __post_init__(self) -> None:
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        try:
            self.service = MetalsExecutionService.from_env(self.history_path)
        except AlpacaMetalsConfigurationError:
            self.service = None

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if self.service is None:
            return JobResult(
                True,
                "Metals cycle deferred",
                {
                    "pillar": PILLAR_METALS,
                    "reason": "alpaca paper credentials unavailable",
                },
            )
        histories = self._load_histories(now)
        if not histories:
            return JobResult(True, "Metals cycle found no usable market data", {"pillar": PILLAR_METALS})
        best = self._best_signal(histories)
        if best is None:
            return JobResult(True, "Metals cycle found no qualifying entry", {"pillar": PILLAR_METALS})
        return JobResult(
            True,
            "Metals cycle scanned successfully",
            {"pillar": PILLAR_METALS, "candidate": best.instrument.symbol},
        )

    def _load_histories(self, now: datetime) -> dict[Instrument, list[MarketBar]]:
        end = now.astimezone(UTC)
        start = end - timedelta(days=14)
        histories: dict[Instrument, list[MarketBar]] = {}
        for symbol in self.universe:
            instrument = Instrument(symbol, AssetClass.ETF)
            bars = self.feed.history(instrument, start, end)
            histories[instrument] = bars
        return histories

    def _best_signal(self, histories: dict[Instrument, list[MarketBar]]):
        ranked = self.scanner.rank(histories, top_n=1)
        if not ranked:
            return None
        candidate = ranked[0]
        proposal = self.strategies.sma_cross(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            proposal = self.strategies.breakout(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            proposal = self.strategies.mean_reversion(candidate.instrument, histories[candidate.instrument])
        if proposal is None or proposal.side is not Side.BUY:
            return None
        return candidate


@dataclass
class InternationalPaperTradingJob:
    name: str = "saxo-international-paper-trading"
    cadence_seconds: float = 300.0
    history_path: str = "var/autotrader/international_trades.db"
    search_keywords: str = "Stock"
    # Keep discovery bounded, but do not truncate the provider's eligible
    # SIM listings to the first five results.
    search_top: int = 20

    def __post_init__(self) -> None:
        try:
            self.adapter = SaxoSimAdapter.from_env()
        except Exception:
            self.adapter = None
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        try:
            self.service = InternationalExecutionService.from_env(self.history_path)
        except Exception:
            self.service = None

    def run(self, now: datetime) -> JobResult:
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if self.adapter is None or self.service is None:
            _write_saxo_permission_status(now=now, authenticated=False, read_only=None, error="Saxo SIM credentials unavailable")
            return JobResult(
                True,
                "International AUTH REQUIRED",
                {"state": "AUTH REQUIRED", "error": "Saxo SIM credentials unavailable"},
            )
        try:
            summary = self.adapter.account_summary()
            capabilities = self.adapter.capability_metadata()
            session_capabilities = self.adapter.session_capabilities()
            trade_level = str(session_capabilities.get("TradeLevel") or "")
            auth_level = str(session_capabilities.get("AuthenticationLevel") or "")
            provider_can_trade = auth_level.lower() == "authenticated" and trade_level in {"OrdersOnly", "FullTradingAndChat"}
            read_only = False if provider_can_trade else True
            instruments = self.adapter.search_instruments(
                self.search_keywords,
                asset_types=("Stock",),
                top=self.search_top,
            )
        except Exception as exc:
            error = str(exc)
            if "401" in error or "unauthorized" in error.lower():
                return JobResult(
                    True,
                    "International AUTH REQUIRED",
                    {"state": "AUTH REQUIRED", "error": "Saxo SIM authentication rejected the read-only probe"},
                )
            _write_saxo_permission_status(now=now, authenticated=True, read_only=None, error=error, capabilities=capabilities, session_capabilities={"state": "ERROR"})
            return JobResult(True, "International data probe failed", {"state": "DEGRADED", "error": error})
        if not instruments:
            return JobResult(True, "International cycle found no instruments", {})
        histories: dict[Instrument, list[MarketBar]] = {}
        for item in instruments:
            instrument = Instrument(item.symbol.replace(".", "-"), AssetClass.STOCK)
            try:
                samples = self.adapter.chart_samples(item, count=30)
            except Exception:
                continue
            bars = _bars_from_saxo(samples, instrument)
            if len(bars) >= 8:
                histories[instrument] = bars
        if not histories:
            return JobResult(True, "International cycle found no usable market data", {})
        ranked = self.scanner.rank(histories, top_n=1)
        if not ranked:
            _write_saxo_permission_status(now=now, authenticated=True, read_only=read_only, capabilities=capabilities, session_capabilities=session_capabilities)
            return JobResult(True, "International cycle found no qualifying entry", {})
        candidate = ranked[0].instrument.symbol
        source = next((item for item in instruments if item.symbol.replace('.', '-') == candidate), None)
        precheck: dict[str, object] = {"state": "NOT_RUN"}
        if source is not None and summary.default_account_key:
            try:
                result = self.adapter.precheck_order(
                    {
                        "AccountKey": summary.default_account_key,
                        "Amount": 1,
                        "AssetType": source.asset_type,
                        "BuySell": "Buy",
                        "ManualOrder": False,
                        "FieldGroups": ["Costs", "MarginImpactBuySell"],
                        "OrderDuration": {"DurationType": "DayOrder"},
                        "OrderType": "Market",
                        "Uic": source.uic,
                    }
                )
                precheck = {"state": str(result.get("PreCheckResult") or "UNKNOWN"), "estimated_cash_required": result.get("EstimatedCashRequired"), "estimated_total_cost": result.get("EstimatedTotalCost"), "error": result.get("ErrorInfo"), "disclaimer": bool(result.get("PreTradeDisclaimers"))}
            except Exception as exc:
                precheck = {"state": "ERROR", "error": str(exc)[:240]}
        _write_saxo_permission_status(now=now, authenticated=True, read_only=read_only, shadow_candidate=candidate, precheck=precheck, capabilities=capabilities, session_capabilities=session_capabilities)
        if read_only is not False:
            return JobResult(True, "International shadow candidate blocked by Saxo SIM permissions", {"candidate": candidate, "execution_state": "EXTERNAL ACCOUNT WRITE BLOCK", "rejection": "EXTERNAL_ACCOUNT_WRITE_PERMISSION"})
        return JobResult(True, "International cycle scanned successfully", {"candidate": candidate, "execution_state": "READY / EVALUATING"})
