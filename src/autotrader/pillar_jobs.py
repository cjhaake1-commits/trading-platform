from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from zoneinfo import ZoneInfo

from .brokers.alpaca_metals_paper import AlpacaMetalsConfigurationError
from .brokers.saxo_sim import SaxoSimAdapter
from .capital_allocations import PILLAR_METALS
from .international_trading import InternationalExecutionService
from .marketdata import YahooHistoricalData
from .metals_trading import MetalsExecutionService, MetalsOrderSpec
from .models import AssetClass, Instrument, MarketBar, PortfolioState, Side
from .paper_experiment import PaperExperimentConfig, PaperExperimentLedger, experimental_candidate
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
    calendar_buffer_days: int = 14

    def __post_init__(self) -> None:
        self.feed = YahooHistoricalData()
        self.scanner = CandidateScanner()
        self.strategies = BaselineStrategies()
        self.experiment = PaperExperimentConfig.from_env()
        self.experiment_ledger = PaperExperimentLedger()
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
        readiness = self._readiness(histories, now)
        best = self._best_signal(histories)
        mode = "BASELINE"
        edge = None
        if best is None and self.experiment.enabled:
            best = self._best_experimental_signal(histories)
            mode = "EXPERIMENTAL_PAPER" if best is not None else mode
        if best is None:
            return JobResult(
                True,
                "Metals cycle found no qualifying entry" if all(row["data_valid"] for row in readiness) else "Metals cycle blocked by insufficient history",
                {"pillar": PILLAR_METALS, "history_required": self.required_bars, "history_lookback_days": self.history_lookback_days, "metals_diagnostics": readiness},
            )
        if mode == "EXPERIMENTAL_PAPER":
            candidate, proposal, edge = best
        else:
            candidate, proposal = best

        # This pillar has its own capital silo.  Do not use the shared Alpaca
        # account balance (which includes Stocks/Crypto) to decide Metals
        # capacity, and do not let a previous open Metals trade be duplicated.
        records = self.service.history.records()
        active_symbols = {
            str(record.get("instrument") or "").upper()
            for record in records
            if str(record.get("status") or "") in {"approved", "executed"}
            and not record.get("closed_at")
        }
        deployed = sum(
            abs(float(record.get("fill_price") or record.get("proposed_entry") or 0.0))
            * float(record.get("quantity") or 0.0)
            for record in records
            if str(record.get("status") or "") in {"approved", "executed"}
            and not record.get("closed_at")
        )
        if proposal.symbol.upper() in active_symbols:
            return JobResult(
                True,
                "Metals cycle skipped duplicate active position",
                {"pillar": PILLAR_METALS, "candidate": candidate.instrument.symbol, "rejection": "DUPLICATE_ACTIVE_POSITION", "deployed": deployed},
            )
        if mode == "EXPERIMENTAL_PAPER" and deployed >= 750.0:
            return JobResult(True, "Metals experimental capital envelope reached", {"pillar": PILLAR_METALS, "candidate": candidate.instrument.symbol, "mode": mode, "rejection": "EXPERIMENTAL_CAPITAL_ENVELOPE", "deployed": deployed, "metals_diagnostics": readiness})
        if mode == "EXPERIMENTAL_PAPER":
            proposal = replace(proposal, requested_quantity=1.0)
        experiment_ledger = getattr(self, "experiment_ledger", None)
        if experiment_ledger is not None:
            experiment_ledger.record_decision(
                pillar=PILLAR_METALS,
                symbol=proposal.symbol,
                strategy=proposal.source,
                timeframe="1d",
                lane=mode,
                decision="candidate",
                entry_price=proposal.entry_price,
                edge=edge,
                features={"score": candidate.score, "rationale": proposal.rationale},
            )
        result = self.service.execute(
            MetalsOrderSpec(proposal=proposal, strategy_version="metals-baseline-v1" if mode == "BASELINE" else "metals-experimental-v1"),
            PortfolioState(equity=1000.0, cash=max(1000.0 - deployed, 0.0)),
            metals_deployed=deployed,
            now=now,
        )
        for row in readiness:
            if row["symbol"] == candidate.instrument.symbol:
                row["risk_evaluated"] = True
                row["capital_evaluated"] = True
                row["qualified"] = result.approved
                row["rejection"] = None if result.approved else result.reason
        return JobResult(
            True,
            "Metals cycle submitted paper order" if result.submitted else "Metals candidate rejected",
            {
                "pillar": PILLAR_METALS,
                "candidate": candidate.instrument.symbol,
                "model_valid": True,
                "risk_approved": result.approved,
                "qualified": result.approved,
                "submitted": result.submitted,
                "order_id": result.order_id,
                "rejection": None if result.approved else result.reason,
                "execution_result": result.reason,
                "deployed": deployed,
                "mode": mode,
                "edge": edge.as_dict() if edge else None,
                "history_required": self.required_bars,
                "history_lookback_days": self.history_lookback_days,
                "metals_diagnostics": readiness,
            },
        )

    @property
    def required_bars(self) -> int:
        config = self.strategies.config
        return max(config.slow_window, config.breakout_window + 1, config.zscore_window)

    @property
    def history_lookback_days(self) -> int:
        # Daily market data has roughly five sessions per seven calendar days.
        # Add two session-equivalents for provider gaps plus an explicit holiday/
        # weekend buffer. This is derived from the active strategy requirement.
        session_buffer = ceil(self.required_bars * 2 / 5)
        return ceil(self.required_bars * 7 / 5) + session_buffer + self.calendar_buffer_days

    def _readiness(self, histories: dict[Instrument, list[MarketBar]], now: datetime) -> list[dict[str, object]]:
        rows = []
        for instrument, bars in histories.items():
            candidate = self.scanner.score_instrument(instrument, bars) if bars else None
            proposals = (
                self.strategies.sma_cross(instrument, bars),
                self.strategies.breakout(instrument, bars),
                self.strategies.mean_reversion(instrument, bars),
            ) if len(bars) >= self.required_bars else (None, None, None)
            votes = [proposal.source + ":" + proposal.side.value for proposal in proposals if proposal is not None]
            rows.append({
                "symbol": instrument.symbol,
                "bars_available": len(bars),
                "bars_required": self.required_bars,
                "data_valid": len(bars) >= self.required_bars,
                "latest_bar": bars[-1].timestamp.isoformat() if bars else None,
                "fresh": bool(bars and (now.astimezone(UTC) - bars[-1].timestamp).days <= 3),
                "scanner_score": None if candidate is None else round(candidate.score, 6),
                "strategy_evaluated": len(bars) >= self.required_bars,
                "strategy_vote": ", ".join(votes) if votes else "NO_SIGNAL",
                "risk_evaluated": False,
                "capital_evaluated": False,
                "qualified": False,
                "rejection": None if len(bars) >= self.required_bars else "BLOCKED — INSUFFICIENT HISTORY",
            })
        return rows

    def _load_histories(self, now: datetime) -> dict[Instrument, list[MarketBar]]:
        end = now.astimezone(UTC)
        start = end - timedelta(days=self.history_lookback_days)
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
        return candidate, proposal

    def _best_experimental_signal(self, histories: dict[Instrument, list[MarketBar]]):
        ranked = self.scanner.rank(histories, top_n=len(histories))
        candidates = []
        for candidate in ranked:
            bars = histories[candidate.instrument]
            proposals = (
                self.strategies.sma_cross(candidate.instrument, bars),
                self.strategies.breakout(candidate.instrument, bars),
                self.strategies.mean_reversion(candidate.instrument, bars),
            )
            selected = experimental_candidate(candidate, proposals, config=self.experiment)
            if selected is not None:
                proposal, edge = selected
                candidates.append((candidate, replace(proposal, confidence=min(proposal.confidence, 0.60)), edge))
        return candidates[0] if candidates else None


@dataclass
class InternationalPaperTradingJob:
    name: str = "saxo-international-paper-trading"
    cadence_seconds: float = 300.0
    history_path: str = "var/autotrader/international_trades.db"
    search_keywords: str = "Stock"
    # Keep discovery bounded, but do not truncate the provider's eligible
    # SIM listings to the first five results.
    search_top: int = 20
    discovery_queries: tuple[str, ...] = ("Stock", "Europe", "Australia", "London", "Japan", "Asia")

    @staticmethod
    def _venue_session(exchange_id: str, now: datetime) -> str:
        exchange = exchange_id.upper()
        if exchange == "ASX":
            zone, start, end = "Australia/Sydney", (10, 0), (16, 0)
        elif exchange in {"TSE", "TYO", "HKEX", "SEHK"}:
            zone, start, end = "Asia/Tokyo", (9, 0), (15, 0)
        elif exchange in {"LSE_SETS", "LSE_SEAQ", "FSE", "MIL", "FFT", "WSE", "VIE", "BME", "OSE"}:
            zone, start, end = "Europe/Berlin", (9, 0), (17, 30)
        elif exchange in {"NASDAQ", "NYSE", "ARCA"}:
            zone, start, end = "America/New_York", (9, 30), (16, 0)
        else:
            return "UNKNOWN"
        local = now.astimezone(ZoneInfo(zone))
        return "OPEN" if local.weekday() < 5 and (start <= (local.hour, local.minute) < end) else "CLOSED"

    @staticmethod
    def _is_foreign(exchange_id: str) -> bool:
        return exchange_id.upper() not in {"NASDAQ", "NYSE", "ARCA"}

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
            discovered = {}
            for query in self.discovery_queries:
                for item in self.adapter.search_instruments(query, asset_types=("Stock",), top=self.search_top):
                    discovered[(item.uic, item.asset_type)] = item
            instruments = tuple(discovered.values())
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
        open_instruments = tuple(
            item for item in instruments
            if self._is_foreign(item.exchange_id or "")
            and self._venue_session(item.exchange_id or "", now) == "OPEN"
        )
        discovery = {
            "venues_discovered": len({item.exchange_id for item in instruments if item.exchange_id}),
            "venues_open": len({item.exchange_id for item in open_instruments if item.exchange_id}),
            "instruments_discovered": len(instruments),
            "instruments_evaluated": len(open_instruments),
        }
        if not open_instruments:
            return JobResult(True, "International waiting for open foreign venue", {
                **discovery, "state": "READY — WAITING FOR ELIGIBLE MARKET SESSION"
            })
        histories: dict[Instrument, list[MarketBar]] = {}
        for item in open_instruments:
            instrument = Instrument(item.symbol.replace(".", "-"), AssetClass.STOCK)
            try:
                samples = self.adapter.chart_samples(item, count=30)
            except Exception:
                continue
            bars = _bars_from_saxo(samples, instrument)
            if len(bars) >= 8:
                histories[instrument] = bars
        if not histories:
            return JobResult(True, "International open venues had no usable market data", {
                **discovery, "state": "DEGRADED — DATA"
            })
        ranked = self.scanner.rank(histories, top_n=1)
        if not ranked:
            _write_saxo_permission_status(now=now, authenticated=True, read_only=read_only, capabilities=capabilities, session_capabilities=session_capabilities)
            return JobResult(True, "International cycle found no qualifying entry", {})
        candidate = ranked[0].instrument.symbol
        source = next((item for item in open_instruments if item.symbol.replace('.', '-') == candidate), None)
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
        return JobResult(True, "International cycle scanned successfully", {
            **discovery, "candidate": candidate, "execution_state": "READY / EVALUATING"
        })
