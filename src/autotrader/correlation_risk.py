from __future__ import annotations

from dataclasses import dataclass

from .models import PortfolioState, TradeProposal


@dataclass(frozen=True)
class CorrelationBucketPolicy:
    max_bucket_notional_pct: float = 0.50
    soft_bucket_notional_pct: float = 0.35
    soft_risk_scale: float = 0.50


@dataclass(frozen=True)
class CorrelationAssessment:
    bucket: str
    current_notional: float
    projected_notional: float
    risk_scale: float
    blocked: bool
    reason: str


class CorrelationBucketEngine:
    """Limit hidden concentration among economically correlated instruments.

    Static bucket labels are intentionally simple and auditable. A later
    covariance model may provide dynamic buckets, but it should still resolve to
    the same deterministic exposure interface before execution.
    """

    def __init__(
        self,
        symbol_buckets: dict[str, str] | None = None,
        policy: CorrelationBucketPolicy | None = None,
    ) -> None:
        self.symbol_buckets = {key.upper(): value for key, value in (symbol_buckets or {}).items()}
        self.policy = policy or CorrelationBucketPolicy()

    def bucket_for(self, symbol: str) -> str:
        return self.symbol_buckets.get(symbol.upper(), symbol.upper())

    def bucket_notional(
        self,
        portfolio: PortfolioState,
        *,
        bucket: str,
        mark_prices: dict[str, float],
    ) -> float:
        total = 0.0
        for symbol, position in portfolio.positions.items():
            if self.bucket_for(symbol) != bucket:
                continue
            price = mark_prices.get(symbol, position.average_price)
            total += abs(position.quantity * price)
        return total

    def assess(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
        *,
        proposed_quantity: float,
        mark_prices: dict[str, float] | None = None,
    ) -> CorrelationAssessment:
        marks = mark_prices or {}
        bucket = self.bucket_for(proposal.symbol)
        current = self.bucket_notional(portfolio, bucket=bucket, mark_prices=marks)
        projected = current + abs(proposed_quantity * proposal.entry_price)
        hard_limit = portfolio.equity * self.policy.max_bucket_notional_pct
        soft_limit = portfolio.equity * self.policy.soft_bucket_notional_pct

        if projected > hard_limit:
            return CorrelationAssessment(
                bucket,
                current,
                projected,
                0.0,
                True,
                "correlation bucket hard exposure limit exceeded",
            )
        if projected > soft_limit:
            return CorrelationAssessment(
                bucket,
                current,
                projected,
                self.policy.soft_risk_scale,
                False,
                "correlation bucket soft exposure limit reached",
            )
        return CorrelationAssessment(
            bucket,
            current,
            projected,
            1.0,
            False,
            "correlation bucket capacity available",
        )


def default_symbol_buckets() -> dict[str, str]:
    """Conservative starter buckets, intended to be expanded from validation data."""
    return {
        "SPY": "us_equity_beta",
        "QQQ": "us_equity_beta",
        "IWM": "us_equity_beta",
        "AAPL": "us_mega_cap_growth",
        "MSFT": "us_mega_cap_growth",
        "NVDA": "us_mega_cap_growth",
        "META": "us_mega_cap_growth",
        "GOOGL": "us_mega_cap_growth",
        "EUR/USD": "usd_fx",
        "GBP/USD": "usd_fx",
        "AUD/USD": "usd_fx",
        "NZD/USD": "usd_fx",
        "USD/JPY": "usd_fx",
        "USD/CHF": "usd_fx",
        "USD/CAD": "usd_fx",
        "BTC-USD": "crypto_beta",
        "ETH-USD": "crypto_beta",
    }
