from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from autotrader.alternative_data import AlternativeSignalItem, AlternativeSource


@dataclass(frozen=True)
class QuiverSignalNormalizer:
    """Translate Quiver records into neutral research features."""

    default_confidence: float = 0.55

    def congress(self, ticker: str, records: list[dict[str, Any]]) -> list[AlternativeSignalItem]:
        items: list[AlternativeSignalItem] = []
        for row in records:
            transaction = str(row.get("Transaction", "")).lower()
            score = 0.0
            if "purchase" in transaction or "buy" in transaction:
                score = 0.45
            elif "sale" in transaction or "sell" in transaction:
                score = -0.45
            observed_at = self._parse_datetime(row.get("ReportDate") or row.get("Date"))
            items.append(
                AlternativeSignalItem(
                    symbol=ticker.upper(),
                    source=AlternativeSource.PUBLIC_OFFICIAL_ACTIVITY,
                    observed_at=observed_at,
                    score=score,
                    confidence=self.default_confidence,
                    text=(
                        f"Congress transaction: {row.get('Representative', 'unknown')} "
                        f"{row.get('Transaction', 'unknown')} {ticker.upper()}"
                    ),
                    metadata=row,
                    commercial_use_authorized=True,
                )
            )
        return items

    def government_contracts(
        self, ticker: str, records: list[dict[str, Any]]
    ) -> list[AlternativeSignalItem]:
        items: list[AlternativeSignalItem] = []
        for row in records:
            amount = self._as_float(row.get("Amount"))
            score = 0.15 if amount > 0 else 0.0
            items.append(
                AlternativeSignalItem(
                    symbol=ticker.upper(),
                    source=AlternativeSource.NEWS,
                    observed_at=self._parse_datetime(row.get("Date") or row.get("action_date")),
                    score=score,
                    confidence=0.60,
                    text=f"Government contract activity for {ticker.upper()}",
                    metadata=row,
                )
            )
        return items

    def institutional_holdings(
        self, ticker: str, records: list[dict[str, Any]]
    ) -> list[AlternativeSignalItem]:
        items: list[AlternativeSignalItem] = []
        for row in records:
            change = self._as_float(row.get("Change_Pct") or row.get("Change"))
            if abs(change) <= 1:
                score = max(-0.5, min(0.5, change))
            else:
                score = 0.3 if change > 0 else -0.3
            items.append(
                AlternativeSignalItem(
                    symbol=ticker.upper(),
                    source=AlternativeSource.NEWS,
                    observed_at=self._parse_datetime(row.get("Date") or row.get("ReportPeriod")),
                    score=score,
                    confidence=0.50,
                    text=f"Institutional holding change for {ticker.upper()}",
                    metadata=row,
                )
            )
        return items

    def off_exchange(
        self, ticker: str, records: list[dict[str, Any]]
    ) -> list[AlternativeSignalItem]:
        items: list[AlternativeSignalItem] = []
        for row in records:
            dpi = self._as_float(row.get("DPI"))
            score = max(-0.35, min(0.35, 0.5 - dpi)) if dpi else 0.0
            items.append(
                AlternativeSignalItem(
                    symbol=ticker.upper(),
                    source=AlternativeSource.SOCIAL,
                    observed_at=self._parse_datetime(row.get("Date")),
                    score=score,
                    confidence=0.45,
                    text=f"Off-exchange trading signal for {ticker.upper()}",
                    metadata=row,
                )
            )
        return items

    @staticmethod
    def _parse_datetime(value: object) -> datetime:
        if value is None:
            return datetime.now(UTC)
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text[:10], "%Y-%m-%d")
            except ValueError:
                return datetime.now(UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _as_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
