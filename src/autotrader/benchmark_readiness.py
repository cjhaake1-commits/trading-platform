from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Mapping, Sequence


@dataclass(frozen=True)
class BenchmarkDefinition:
    key: str
    label: str
    category: str
    public_symbol: str
    bloomberg_security: str | None
    purpose: str


DEFAULT_BENCHMARKS: tuple[BenchmarkDefinition, ...] = (
    BenchmarkDefinition("sp500_index", "S&P 500 Index", "index", "^GSPC", "SPX Index", "broad US equity"),
    BenchmarkDefinition("nasdaq100_index", "Nasdaq-100 Index", "index", "^NDX", "NDX Index", "large-cap growth"),
    BenchmarkDefinition("dow_index", "Dow Jones Industrial Average", "index", "^DJI", "INDU Index", "US blue chips"),
    BenchmarkDefinition("russell2000_index", "Russell 2000 Index", "index", "^RUT", "RTY Index", "US small caps"),
    BenchmarkDefinition("spy", "SPDR S&P 500 ETF Trust", "etf", "SPY", "SPY US Equity", "large liquid S&P 500 ETF"),
    BenchmarkDefinition("voo", "Vanguard S&P 500 ETF", "etf", "VOO", "VOO US Equity", "low-cost S&P 500 ETF"),
    BenchmarkDefinition("qqq", "Invesco QQQ Trust", "etf", "QQQ", "QQQ US Equity", "Nasdaq-100 ETF"),
    BenchmarkDefinition("vti", "Vanguard Total Stock Market ETF", "etf", "VTI", "VTI US Equity", "total US equity"),
    BenchmarkDefinition("iwm", "iShares Russell 2000 ETF", "etf", "IWM", "IWM US Equity", "US small-cap ETF"),
    BenchmarkDefinition("vt", "Vanguard Total World Stock ETF", "etf", "VT", "VT US Equity", "global equity"),
    BenchmarkDefinition("agg", "iShares Core U.S. Aggregate Bond ETF", "etf", "AGG", "AGG US Equity", "investment-grade bonds"),
    BenchmarkDefinition("gld", "SPDR Gold Shares", "etf", "GLD", "GLD US Equity", "gold exposure"),
    BenchmarkDefinition("bil", "SPDR Bloomberg 1-3 Month T-Bill ETF", "etf", "BIL", "BIL US Equity", "cash hurdle"),
    BenchmarkDefinition("vfiax", "Vanguard 500 Index Fund Admiral", "mutual_fund", "VFIAX", "VFIAX US Equity", "S&P 500 mutual-fund comparator"),
    BenchmarkDefinition("vtsax", "Vanguard Total Stock Market Index Admiral", "mutual_fund", "VTSAX", "VTSAX US Equity", "total-market mutual-fund comparator"),
    BenchmarkDefinition("fxaix", "Fidelity 500 Index Fund", "mutual_fund", "FXAIX", "FXAIX US Equity", "S&P 500 mutual-fund comparator"),
    BenchmarkDefinition("fskax", "Fidelity Total Market Index Fund", "mutual_fund", "FSKAX", "FSKAX US Equity", "total-market mutual-fund comparator"),
    BenchmarkDefinition("swppx", "Schwab S&P 500 Index Fund", "mutual_fund", "SWPPX", "SWPPX US Equity", "S&P 500 mutual-fund comparator"),
    BenchmarkDefinition("btc", "Bitcoin", "crypto", "BTC-USD", None, "crypto pillar hurdle"),
    BenchmarkDefinition("eth", "Ether", "crypto", "ETH-USD", None, "crypto pillar hurdle"),
)


@dataclass(frozen=True)
class BenchmarkReadinessPolicy:
    """Minimum paper evidence required before live-capital review can begin.

    Passing this policy never enables live trading. It only establishes that a
    paper strategy has earned a formal human/legal/risk review.
    """

    minimum_observation_days: int = 126
    minimum_completed_trades: int = 100
    minimum_market_regimes: int = 3
    minimum_data_coverage: float = 0.95
    minimum_benchmark_outperformance_ratio: float = 0.70
    minimum_rolling_outperformance_ratio: float = 0.70
    minimum_rolling_windows: int = 12
    maximum_absolute_drawdown: float = 0.20
    maximum_drawdown_disadvantage: float = 0.05

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BenchmarkReadinessPolicy":
        source = os.environ if env is None else env

        def integer(name: str, default: int) -> int:
            try:
                return int(source.get(name, str(default)))
            except (TypeError, ValueError):
                return default

        def number(name: str, default: float) -> float:
            try:
                return float(source.get(name, str(default)))
            except (TypeError, ValueError):
                return default

        return cls(
            minimum_observation_days=integer("LIVE_READINESS_MIN_PAPER_DAYS", 126),
            minimum_completed_trades=integer("LIVE_READINESS_MIN_COMPLETED_TRADES", 100),
            minimum_market_regimes=integer("LIVE_READINESS_MIN_MARKET_REGIMES", 3),
            minimum_data_coverage=number("LIVE_READINESS_MIN_DATA_COVERAGE", 0.95),
            minimum_benchmark_outperformance_ratio=number(
                "LIVE_READINESS_MIN_BENCHMARK_OUTPERFORMANCE", 0.70
            ),
            minimum_rolling_outperformance_ratio=number(
                "LIVE_READINESS_MIN_ROLLING_OUTPERFORMANCE", 0.70
            ),
            minimum_rolling_windows=integer("LIVE_READINESS_MIN_ROLLING_WINDOWS", 12),
            maximum_absolute_drawdown=number("LIVE_READINESS_MAX_DRAWDOWN", 0.20),
            maximum_drawdown_disadvantage=number(
                "LIVE_READINESS_MAX_DRAWDOWN_DISADVANTAGE", 0.05
            ),
        )


@dataclass(frozen=True)
class PaperPerformanceEvidence:
    observation_days: int
    completed_trades: int
    observed_market_regimes: int
    data_coverage: float
    strategy_total_return: float
    strategy_max_drawdown: float
    benchmark_total_returns: Mapping[str, float] = field(default_factory=dict)
    benchmark_max_drawdowns: Mapping[str, float] = field(default_factory=dict)
    rolling_strategy_returns: Sequence[float] = field(default_factory=tuple)
    rolling_benchmark_returns: Mapping[str, Sequence[float]] = field(default_factory=dict)
    accounting_verified: bool = False
    cost_model_complete: bool = False
    stress_tests_passed: bool = False
    data_lineage_complete: bool = False


@dataclass(frozen=True)
class BenchmarkReadinessAssessment:
    state: str
    benchmark_outperformance_ratio: float
    rolling_outperformance_ratio: float
    median_benchmark_return: float | None
    median_benchmark_drawdown: float | None
    reasons: tuple[str, ...]
    live_transition_allowed: bool = False
    human_approval_required: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _rolling_composite(returns: Mapping[str, Sequence[float]], index: int) -> float | None:
    values = [float(series[index]) for series in returns.values() if len(series) > index]
    return median(values) if values else None


def assess_benchmark_readiness(
    evidence: PaperPerformanceEvidence,
    policy: BenchmarkReadinessPolicy | None = None,
) -> BenchmarkReadinessAssessment:
    """Assess paper evidence against a diversified benchmark and consistency gate.

    All returns must already be net of realistic fees, slippage, borrow/funding
    costs, and other execution assumptions. This function is pure and cannot
    enable a broker or modify runtime configuration.
    """

    rules = policy or BenchmarkReadinessPolicy()
    reasons: list[str] = []

    integrity_failures = []
    if not evidence.accounting_verified:
        integrity_failures.append("provider/accounting reconciliation is not verified")
    if not evidence.cost_model_complete:
        integrity_failures.append("fees, slippage, borrow/funding, or execution costs are incomplete")
    if not evidence.stress_tests_passed:
        integrity_failures.append("historical and synthetic stress tests have not passed")
    if not evidence.data_lineage_complete:
        integrity_failures.append("data lineage and timestamp provenance are incomplete")
    if evidence.data_coverage < rules.minimum_data_coverage:
        integrity_failures.append(
            f"benchmark/data coverage {evidence.data_coverage:.1%} is below {rules.minimum_data_coverage:.1%}"
        )

    sample_failures = []
    if evidence.observation_days < rules.minimum_observation_days:
        sample_failures.append(
            f"paper history {evidence.observation_days} days is below {rules.minimum_observation_days}"
        )
    if evidence.completed_trades < rules.minimum_completed_trades:
        sample_failures.append(
            f"completed trades {evidence.completed_trades} is below {rules.minimum_completed_trades}"
        )
    if evidence.observed_market_regimes < rules.minimum_market_regimes:
        sample_failures.append(
            f"observed regimes {evidence.observed_market_regimes} is below {rules.minimum_market_regimes}"
        )

    total_benchmarks = {key: float(value) for key, value in evidence.benchmark_total_returns.items()}
    median_benchmark_return = median(total_benchmarks.values()) if total_benchmarks else None
    outperformed = sum(
        1 for benchmark_return in total_benchmarks.values()
        if evidence.strategy_total_return > benchmark_return
    )
    benchmark_ratio = _ratio(outperformed, len(total_benchmarks))

    usable_windows = min(
        [len(evidence.rolling_strategy_returns)]
        + [len(values) for values in evidence.rolling_benchmark_returns.values()]
    ) if evidence.rolling_benchmark_returns and evidence.rolling_strategy_returns else 0
    rolling_wins = 0
    for index in range(usable_windows):
        composite = _rolling_composite(evidence.rolling_benchmark_returns, index)
        if composite is not None and float(evidence.rolling_strategy_returns[index]) > composite:
            rolling_wins += 1
    rolling_ratio = _ratio(rolling_wins, usable_windows)

    drawdowns = {key: abs(float(value)) for key, value in evidence.benchmark_max_drawdowns.items()}
    median_benchmark_drawdown = median(drawdowns.values()) if drawdowns else None

    performance_failures = []
    if not total_benchmarks:
        performance_failures.append("no benchmark total-return evidence is available")
    elif benchmark_ratio < rules.minimum_benchmark_outperformance_ratio:
        performance_failures.append(
            f"strategy beat {benchmark_ratio:.1%} of total-return benchmarks; required {rules.minimum_benchmark_outperformance_ratio:.1%}"
        )
    if median_benchmark_return is not None and evidence.strategy_total_return <= median_benchmark_return:
        performance_failures.append("strategy total return does not exceed the median benchmark return")
    if usable_windows < rules.minimum_rolling_windows:
        performance_failures.append(
            f"rolling windows {usable_windows} is below {rules.minimum_rolling_windows}"
        )
    elif rolling_ratio < rules.minimum_rolling_outperformance_ratio:
        performance_failures.append(
            f"strategy beat the rolling benchmark composite in {rolling_ratio:.1%} of windows; required {rules.minimum_rolling_outperformance_ratio:.1%}"
        )
    if evidence.strategy_max_drawdown > rules.maximum_absolute_drawdown:
        performance_failures.append(
            f"strategy drawdown {evidence.strategy_max_drawdown:.1%} exceeds {rules.maximum_absolute_drawdown:.1%}"
        )
    if (
        median_benchmark_drawdown is not None
        and evidence.strategy_max_drawdown
        > median_benchmark_drawdown + rules.maximum_drawdown_disadvantage
    ):
        performance_failures.append(
            "strategy drawdown is materially worse than the benchmark median"
        )

    if integrity_failures:
        state = "BLOCKED_DATA_INTEGRITY"
        reasons.extend(integrity_failures)
        reasons.extend(sample_failures)
        reasons.extend(performance_failures)
    elif sample_failures:
        state = "LEARNING"
        reasons.extend(sample_failures)
        reasons.extend(performance_failures)
    elif performance_failures:
        state = "BENCHMARK_DEVELOPING"
        reasons.extend(performance_failures)
    else:
        state = "PAPER_EDGE_CONFIRMED"
        reasons.append(
            "paper evidence passed diversified total-return, rolling consistency, drawdown, stress, cost, and lineage gates"
        )

    reasons.append(
        "live trading remains disabled; passing paper evidence only permits a separate human, legal, operational, and risk review"
    )
    return BenchmarkReadinessAssessment(
        state=state,
        benchmark_outperformance_ratio=benchmark_ratio,
        rolling_outperformance_ratio=rolling_ratio,
        median_benchmark_return=median_benchmark_return,
        median_benchmark_drawdown=median_benchmark_drawdown,
        reasons=tuple(dict.fromkeys(reasons)),
    )
