from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from .models import PortfolioState


@dataclass(frozen=True)
class BrokerPosition:
    broker: str
    symbol: str
    quantity: float
    average_price: float | None = None


@dataclass(frozen=True)
class ReconciliationIssue:
    symbol: str
    kind: str
    ledger_quantity: float
    broker_quantity: float
    reason: str


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    issues: tuple[ReconciliationIssue, ...]
    reason: str


class PositionReconciler:
    """Compare persisted logical positions to broker truth after startup/reconnect.

    Reconciliation is intentionally fail closed. A discrepancy must be resolved
    or explicitly acknowledged before the system can create new exposure.
    """

    def __init__(self, *, quantity_tolerance: float = 1e-8) -> None:
        if quantity_tolerance < 0:
            raise ValueError("quantity_tolerance cannot be negative")
        self.quantity_tolerance = quantity_tolerance

    def reconcile(
        self,
        portfolio: PortfolioState,
        broker_positions: list[BrokerPosition],
    ) -> ReconciliationResult:
        broker_by_symbol: dict[str, float] = {}
        for position in broker_positions:
            broker_by_symbol[position.symbol] = (
                broker_by_symbol.get(position.symbol, 0.0) + position.quantity
            )

        ledger_symbols = set(portfolio.positions)
        broker_symbols = {
            symbol
            for symbol, quantity in broker_by_symbol.items()
            if abs(quantity) > self.quantity_tolerance
        }
        issues: list[ReconciliationIssue] = []

        for symbol in sorted(ledger_symbols | broker_symbols):
            ledger_quantity = (
                portfolio.positions.get(symbol).quantity if symbol in portfolio.positions else 0.0
            )
            broker_quantity = broker_by_symbol.get(symbol, 0.0)
            if isclose(
                ledger_quantity,
                broker_quantity,
                rel_tol=0.0,
                abs_tol=self.quantity_tolerance,
            ):
                continue
            if ledger_quantity == 0:
                kind = "broker_only_position"
                reason = "broker has exposure absent from persistent ledger"
            elif broker_quantity == 0:
                kind = "ledger_only_position"
                reason = "ledger has exposure absent from broker"
            else:
                kind = "quantity_mismatch"
                reason = "broker and ledger quantities disagree"
            issues.append(
                ReconciliationIssue(
                    symbol=symbol,
                    kind=kind,
                    ledger_quantity=ledger_quantity,
                    broker_quantity=broker_quantity,
                    reason=reason,
                )
            )

        if issues:
            return ReconciliationResult(
                False,
                tuple(issues),
                "position reconciliation failed; new exposure must remain blocked",
            )
        return ReconciliationResult(True, (), "broker and ledger positions reconcile")


def normalize_alpaca_positions(records: object) -> list[BrokerPosition]:
    if not isinstance(records, list):
        return []
    output: list[BrokerPosition] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        qty = row.get("qty")
        if symbol is None or qty is None:
            continue
        side = str(row.get("side") or "long").lower()
        quantity = float(qty)
        if side == "short":
            quantity = -abs(quantity)
        output.append(
            BrokerPosition(
                broker="alpaca-paper",
                symbol=str(symbol).upper(),
                quantity=quantity,
                average_price=(
                    None if row.get("avg_entry_price") is None else float(row["avg_entry_price"])
                ),
            )
        )
    return output


def normalize_oanda_positions(records: object) -> list[BrokerPosition]:
    if not isinstance(records, list):
        return []
    output: list[BrokerPosition] = []
    for row in records:
        if not isinstance(row, dict) or row.get("instrument") is None:
            continue
        symbol = str(row["instrument"]).replace("_", "/").upper()
        long = row.get("long") if isinstance(row.get("long"), dict) else {}
        short = row.get("short") if isinstance(row.get("short"), dict) else {}
        long_units = float(long.get("units", 0) or 0)
        short_units = float(short.get("units", 0) or 0)
        quantity = long_units + short_units
        average = long.get("averagePrice") if quantity >= 0 else short.get("averagePrice")
        if abs(quantity) <= 1e-12:
            continue
        output.append(
            BrokerPosition(
                broker="oanda-practice",
                symbol=symbol,
                quantity=quantity,
                average_price=None if average is None else float(average),
            )
        )
    return output
