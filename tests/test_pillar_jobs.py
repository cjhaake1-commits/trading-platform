from datetime import UTC, datetime, timedelta

from autotrader.models import AssetClass, Instrument, MarketBar, PortfolioState, Side
from autotrader.pillar_jobs import MetalsPaperTradingJob
from autotrader.runtime import JobResult
from autotrader.scanner import CandidateScanner
from autotrader.strategies import BaselineStrategies


def _history(symbol: str) -> list[MarketBar]:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    return [
        MarketBar(
            symbol=symbol,
            asset_class=AssetClass.ETF,
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1000,
        )
        for index in range(25)
    ]


class _History:
    def records(self):
        return []


class _Service:
    def __init__(self):
        self.history = _History()
        self.calls = []

    def execute(self, spec, portfolio: PortfolioState, *, metals_deployed, now):
        self.calls.append((spec, portfolio, metals_deployed, now))
        return type("Result", (), {
            "approved": True,
            "submitted": True,
            "reason": "accepted",
            "order_id": "paper-order",
        })()


def test_metals_job_reaches_existing_execution_service_for_buy_candidate():
    job = MetalsPaperTradingJob.__new__(MetalsPaperTradingJob)
    job.service = _Service()
    job.scanner = CandidateScanner()
    job.strategies = BaselineStrategies()
    job.universe = ("GLD",)
    job._load_histories = lambda now: {Instrument("GLD", AssetClass.ETF): _history("GLD")}

    result = job.run(datetime(2026, 8, 24, tzinfo=UTC))

    assert isinstance(result, JobResult)
    assert result.data["qualified"] is True
    assert result.data["submitted"] is True
    assert len(job.service.calls) == 1
    assert job.service.calls[0][0].proposal.side is Side.BUY
    assert job.service.calls[0][1].equity == 1000.0
    assert job.service.calls[0][2] == 0.0


def test_metals_history_window_is_derived_from_strategy_lookbacks():
    job = MetalsPaperTradingJob.__new__(MetalsPaperTradingJob)
    job.strategies = BaselineStrategies()
    job.calendar_buffer_days = 14

    assert job.required_bars == 21
    assert job.history_lookback_days >= 35


def test_metals_history_request_covers_weekends_and_provider_gaps():
    job = MetalsPaperTradingJob.__new__(MetalsPaperTradingJob)
    job.strategies = BaselineStrategies()
    job.calendar_buffer_days = 14
    captured = {}

    class Feed:
        def history(self, instrument, start, end):
            captured[instrument.symbol] = (start, end)
            return _history(instrument.symbol)

    job.feed = Feed()
    job.universe = ("GLD",)
    result = job._load_histories(datetime(2026, 8, 24, tzinfo=UTC))

    assert len(result[Instrument("GLD", AssetClass.ETF)]) == 25
    assert (captured["GLD"][1] - captured["GLD"][0]).days == job.history_lookback_days


def test_metals_insufficient_history_is_explicitly_data_readiness_blocked():
    job = MetalsPaperTradingJob.__new__(MetalsPaperTradingJob)
    job.strategies = BaselineStrategies()
    job.scanner = CandidateScanner()
    job.universe = ("GLD",)
    job.service = None
    job._load_histories = lambda now: {Instrument("GLD", AssetClass.ETF): _history("GLD")[:11]}

    result = job._readiness(job._load_histories(datetime(2026, 8, 24, tzinfo=UTC)), datetime(2026, 8, 24, tzinfo=UTC))

    assert result[0]["data_valid"] is False
    assert result[0]["strategy_evaluated"] is False
    assert result[0]["rejection"] == "BLOCKED — INSUFFICIENT HISTORY"
