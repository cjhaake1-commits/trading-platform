from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from statistics import fmean

from .public_market_intelligence import PublicIntelligenceStore

TOKEN = re.compile(r"[a-z][a-z0-9$-]{2,}")
STOPWORDS = frozenset(
    "about after again against because being between could from have into more most other over same such than that their there these they this through under very what when where which while will with would".split()
)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _tokens(text: str) -> set[str]:
    return {token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS}


def _feature(
    now: datetime,
    name: str,
    source: str,
    value: float,
    sample_size: int,
    *,
    symbol: str | None = None,
    horizon: int | None = None,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "feature_time": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "feature_name": name,
        "source": source,
        "symbol": symbol,
        "horizon_seconds": horizon,
        "value": float(value),
        "sample_size": int(sample_size),
        "metadata": dict(metadata or {}),
    }


class DerivedIntelligenceEngine:
    """Convert public observations into research features; never broker instructions."""

    def __init__(self, store: PublicIntelligenceStore) -> None:
        self.store = store

    def _coinbase(self, now: datetime) -> list[dict[str, object]]:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in reversed(self.store.observations(source="coinbase", limit=20_000)):
            if row.get("symbol"):
                grouped[str(row["symbol"])].append(row)
        features: list[dict[str, object]] = []
        for symbol, rows in grouped.items():
            recent = rows[-500:]
            spreads: list[float] = []
            imbalances: list[float] = []
            prices: list[float] = []
            for row in recent:
                meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                bid = _number(meta.get("best_bid"))
                ask = _number(meta.get("best_ask"))
                price = _number(row.get("value"))
                if price is not None:
                    prices.append(price)
                if bid and ask and ask >= bid:
                    midpoint = (ask + bid) / 2
                    if midpoint:
                        spreads.append((ask - bid) / midpoint * 10_000)
                for bid_key, ask_key in (("bids", "asks"),):
                    bids = meta.get(bid_key)
                    asks = meta.get(ask_key)
                    if isinstance(bids, list) and isinstance(asks, list):
                        bid_size = sum(_number(level[1]) or 0 for level in bids[:10] if isinstance(level, list) and len(level) > 1)
                        ask_size = sum(_number(level[1]) or 0 for level in asks[:10] if isinstance(level, list) and len(level) > 1)
                        total = bid_size + ask_size
                        if total:
                            imbalances.append((bid_size - ask_size) / total)
            if spreads:
                features.append(_feature(now, "spread_bps", "coinbase", fmean(spreads), len(spreads), symbol=symbol))
            if imbalances:
                features.append(
                    _feature(now, "order_book_imbalance", "coinbase", fmean(imbalances), len(imbalances), symbol=symbol)
                )
            half = max(1, len(recent) // 2)
            older_count = max(1, len(recent[:half]))
            acceleration = len(recent[half:]) / older_count
            features.append(_feature(now, "message_acceleration", "coinbase", acceleration, len(recent), symbol=symbol))
            if len(prices) >= 2 and prices[0]:
                features.append(
                    _feature(now, "sample_return", "coinbase", prices[-1] / prices[0] - 1, len(prices), symbol=symbol)
                )
        return features

    def _narratives(self, now: datetime) -> list[dict[str, object]]:
        features: list[dict[str, object]] = []
        for source, event_type in (("bluesky", "social_post"), ("gdelt", "global_news")):
            rows = list(reversed(self.store.observations(source=source, event_type=event_type, limit=5000)))
            if not rows:
                continue
            half = max(1, len(rows) // 2)
            old, new = rows[:half], rows[half:]
            old_counts: Counter[str] = Counter()
            new_counts: Counter[str] = Counter()
            for row in old:
                old_counts.update(_tokens(str(row.get("title") or "")))
            for row in new:
                new_counts.update(_tokens(str(row.get("title") or "")))
            for term, count in new_counts.most_common(25):
                previous = old_counts[term]
                velocity = (count + 1) / (previous + 1)
                features.append(
                    _feature(
                        now, "mention_velocity", source, velocity, count + previous,
                        symbol=term, metadata={"term": term, "recent": count, "previous": previous},
                    )
                )
            token_sets = [_tokens(str(row.get("title") or "")) for row in new[-250:]]
            clustered = sum(1 for left, right in zip(token_sets, token_sets[1:], strict=False) if len(left & right) >= 2)
            if token_sets:
                features.append(
                    _feature(now, "event_cluster_density", source, clustered / len(token_sets), len(token_sets))
                )
        return features

    def _cross_asset(self, now: datetime) -> list[dict[str, object]]:
        returns: dict[str, list[float]] = defaultdict(list)
        for row in reversed(self.store.observations(source="coinbase", limit=20_000)):
            symbol = str(row.get("symbol") or "")
            value = _number(row.get("value"))
            if symbol and value is not None:
                returns[symbol].append(value)
        features: list[dict[str, object]] = []
        symbols = sorted(returns)
        for leader in symbols:
            for follower in symbols:
                if leader >= follower:
                    continue
                left, right = returns[leader][-250:], returns[follower][-250:]
                size = min(len(left), len(right))
                if size < 12:
                    continue
                left_change = [left[i] / left[i - 1] - 1 for i in range(1, size) if left[i - 1]]
                right_change = [right[i] / right[i - 1] - 1 for i in range(1, size) if right[i - 1]]
                n = min(len(left_change), len(right_change))
                if n < 10:
                    continue
                x, y = left_change[: n - 1], right_change[1:n]
                mx, my = fmean(x), fmean(y)
                numerator = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
                denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
                correlation = numerator / denominator if denominator else 0.0
                features.append(
                    _feature(
                        now, "lead_lag_correlation", "coinbase", correlation, len(x), symbol=f"{leader}>{follower}",
                        metadata={"leader": leader, "follower": follower, "lag_events": 1},
                    )
                )
        return features

    def _source_return_attribution(self, now: datetime) -> list[dict[str, object]]:
        """Score contemporaneous source activity against sampled returns.

        This is an attribution candidate for later validation, not a causal claim.
        """
        sampled_returns: dict[str, float] = {}
        prices: dict[str, list[float]] = defaultdict(list)
        for row in reversed(self.store.observations(source="coinbase", limit=20_000)):
            symbol = str(row.get("symbol") or "")
            value = _number(row.get("value"))
            if symbol and value is not None:
                prices[symbol].append(value)
        for symbol, values in prices.items():
            window = values[-500:]
            if len(window) >= 2 and window[0]:
                sampled_returns[symbol] = window[-1] / window[0] - 1

        features: list[dict[str, object]] = []
        for source, event_type in (("bluesky", "social_post"), ("gdelt", "global_news")):
            rows = self.store.observations(source=source, event_type=event_type, limit=5000)
            if len(rows) < 2:
                continue
            recent_count = max(1, len(rows) // 2)
            prior_count = max(1, len(rows) - recent_count)
            activity_ratio = recent_count / prior_count
            for symbol, sampled_return in sampled_returns.items():
                features.append(
                    _feature(
                        now,
                        "source_to_return_attribution",
                        source,
                        sampled_return * math.log1p(activity_ratio),
                        len(rows),
                        symbol=symbol,
                        metadata={
                            "activity_ratio": activity_ratio,
                            "sample_return": sampled_return,
                            "method": "contemporaneous_activity_weighted_return",
                            "causal": False,
                        },
                    )
                )
        return features

    def run(self, now: datetime | None = None) -> dict[str, object]:
        observed = now or datetime.now(UTC)
        rows = (
            self._coinbase(observed)
            + self._narratives(observed)
            + self._cross_asset(observed)
            + self._source_return_attribution(observed)
        )
        written = self.store.append_features(rows)
        counts = Counter(str(row["feature_name"]) for row in rows)
        return {
            "state": "ACTIVE" if written else "IDLE",
            "features_written": written,
            "feature_counts": dict(sorted(counts.items())),
            "research_only": True,
            "broker_control": False,
            "generated_at": observed.astimezone(UTC).isoformat(),
        }
