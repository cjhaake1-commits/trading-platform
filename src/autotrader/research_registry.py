from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import mean


class ResearchLane(StrEnum):
    FAST_FEATURES = "fast_features"
    TRADING_AGENTS = "trading_agents"
    QLIB = "qlib"
    RD_AGENT = "rd_agent"
    FINRL = "finrl"
    FINGPT = "fingpt"
    FINROBOT = "finrobot"
    ALTERNATIVE_DATA = "alternative_data"


class ChallengerStatus(StrEnum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    CHAMPION = "champion"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ResearchSignal:
    lane: ResearchLane
    model_id: str
    symbol: str
    score: float
    confidence: float
    horizon_seconds: int
    generated_at: datetime
    information_available_at: datetime
    source_version: str
    feature_version: str = ""
    rationale: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError("score must be between -1 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be positive")
        if self.information_available_at > self.generated_at:
            raise ValueError("information cannot become available after signal generation")


@dataclass(frozen=True)
class ValidationMetrics:
    observations: int
    net_return_pct: float
    max_drawdown_pct: float
    sharpe: float | None = None
    win_rate: float | None = None
    turnover: float | None = None
    average_slippage_bps: float | None = None
    p95_latency_ms: float | None = None
    baseline_net_return_pct: float | None = None
    incremental_net_return_pct: float | None = None


@dataclass(frozen=True)
class PromotionPolicy:
    min_observations: int = 100
    min_incremental_return_pct: float = 0.0
    max_drawdown_pct: float = 15.0
    max_average_slippage_bps: float = 20.0
    max_p95_latency_ms: float = 2000.0
    require_positive_net_return: bool = True


@dataclass
class ChallengerRecord:
    lane: ResearchLane
    model_id: str
    source_version: str
    status: ChallengerStatus = ChallengerStatus.RESEARCH
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metrics_history: list[ValidationMetrics] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def latest_metrics(self) -> ValidationMetrics | None:
        return self.metrics_history[-1] if self.metrics_history else None


class ResearchRegistry:
    """Track independent research lanes and gate their promotion.

    The registry deliberately does not place orders. It records model provenance,
    validation evidence, and promotion state so external frameworks remain
    challengers until they demonstrate incremental out-of-sample value.
    """

    def __init__(self, policy: PromotionPolicy | None = None):
        self.policy = policy or PromotionPolicy()
        self._records: dict[tuple[ResearchLane, str], ChallengerRecord] = {}

    def register(
        self,
        lane: ResearchLane,
        model_id: str,
        source_version: str,
        *,
        notes: str | None = None,
    ) -> ChallengerRecord:
        key = (lane, model_id)
        record = self._records.get(key)
        if record is None:
            record = ChallengerRecord(lane=lane, model_id=model_id, source_version=source_version)
            self._records[key] = record
        elif record.source_version != source_version:
            raise ValueError("model_id already exists with a different source_version")
        if notes:
            record.notes.append(notes)
        return record

    def record_metrics(
        self,
        lane: ResearchLane,
        model_id: str,
        metrics: ValidationMetrics,
    ) -> ChallengerRecord:
        record = self._records[(lane, model_id)]
        record.metrics_history.append(metrics)
        return record

    def promotion_failures(self, metrics: ValidationMetrics) -> list[str]:
        failures: list[str] = []
        policy = self.policy
        if metrics.observations < policy.min_observations:
            failures.append("insufficient observations")
        if policy.require_positive_net_return and metrics.net_return_pct <= 0:
            failures.append("net return is not positive")
        if metrics.incremental_net_return_pct is None:
            failures.append("incremental return versus baseline is missing")
        elif metrics.incremental_net_return_pct <= policy.min_incremental_return_pct:
            failures.append("insufficient incremental return versus baseline")
        if metrics.max_drawdown_pct > policy.max_drawdown_pct:
            failures.append("drawdown exceeds policy")
        if (
            metrics.average_slippage_bps is not None
            and metrics.average_slippage_bps > policy.max_average_slippage_bps
        ):
            failures.append("slippage exceeds policy")
        if metrics.p95_latency_ms is not None and metrics.p95_latency_ms > policy.max_p95_latency_ms:
            failures.append("latency exceeds policy")
        return failures

    def eligible_for_paper(self, lane: ResearchLane, model_id: str) -> bool:
        record = self._records[(lane, model_id)]
        metrics = record.latest_metrics
        return metrics is not None and not self.promotion_failures(metrics)

    def promote_to_paper(self, lane: ResearchLane, model_id: str) -> ChallengerRecord:
        record = self._records[(lane, model_id)]
        metrics = record.latest_metrics
        if metrics is None:
            raise RuntimeError("cannot promote challenger without validation metrics")
        failures = self.promotion_failures(metrics)
        if failures:
            raise RuntimeError("promotion blocked: " + "; ".join(failures))
        record.status = ChallengerStatus.PAPER
        return record

    def reject(self, lane: ResearchLane, model_id: str, reason: str) -> ChallengerRecord:
        record = self._records[(lane, model_id)]
        record.status = ChallengerStatus.REJECTED
        record.notes.append(reason)
        return record

    def records(self) -> list[ChallengerRecord]:
        return list(self._records.values())

    def lane_summary(self) -> dict[str, dict[str, object]]:
        summary: dict[str, dict[str, object]] = {}
        for lane in ResearchLane:
            records = [record for record in self._records.values() if record.lane is lane]
            latest_returns = [
                record.latest_metrics.net_return_pct
                for record in records
                if record.latest_metrics is not None
            ]
            summary[lane.value] = {
                "models": len(records),
                "paper_or_better": sum(
                    record.status in {ChallengerStatus.PAPER, ChallengerStatus.SHADOW, ChallengerStatus.CHAMPION}
                    for record in records
                ),
                "average_latest_net_return_pct": (
                    mean(latest_returns) if latest_returns else None
                ),
            }
        return summary
