from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CorporateSource(StrEnum):
    SEC_COMPANYFACTS = "sec_companyfacts"
    SEC_SUBMISSIONS = "sec_submissions"
    SEC_FILING = "sec_filing"
    INVESTOR_RELATIONS = "investor_relations"
    EXCHANGE_REFERENCE = "exchange_reference"
    CBOE_REFERENCE = "cboe_reference"


class FilingFamily(StrEnum):
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"
    FORM_4 = "4"
    THIRTEEN_F = "13F-HR"
    DEF_14A = "DEF 14A"
    OTHER = "OTHER"


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    name: str
    cik: str | None = None
    exchange: str | None = None
    memberships: tuple[str, ...] = ()
    active: bool = True
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Provenance:
    source: CorporateSource
    source_url: str
    retrieved_at: datetime
    observed_at: datetime
    effective_at: datetime | None = None
    accession_number: str | None = None
    filing_form: str | None = None
    commercial_use_authorized: bool = True

    def __post_init__(self) -> None:
        for value in (self.retrieved_at, self.observed_at, self.effective_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("provenance timestamps must be timezone-aware")


@dataclass(frozen=True)
class FundamentalFact:
    symbol: str
    cik: str | None
    taxonomy: str
    concept: str
    label: str
    value: float | int | str | None
    unit: str | None
    period_start: str | None
    period_end: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed_at: str | None
    frame: str | None
    provenance: Provenance


@dataclass(frozen=True)
class FilingDocument:
    symbol: str
    cik: str | None
    family: FilingFamily
    accession_number: str
    filed_at: str
    period_of_report: str | None
    primary_document: str | None
    items: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


CORE_CONCEPT_GROUPS: dict[str, tuple[str, ...]] = {
    "income_statement": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "CostOfRevenue",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ),
    "balance_sheet": (
        "Assets",
        "AssetsCurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "AccountsReceivableNetCurrent",
        "InventoryNet",
        "PropertyPlantAndEquipmentNet",
        "Goodwill",
        "Liabilities",
        "LiabilitiesCurrent",
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
        "StockholdersEquity",
    ),
    "cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsOfDividends",
    ),
    "capital_allocation": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsOfDividends",
        "ProceedsFromIssuanceOfLongTermDebt",
        "RepaymentsOfLongTermDebt",
    ),
}


class SecCompanyFactsNormalizer:
    """Normalize SEC companyfacts JSON without inventing missing values.

    The SEC taxonomy evolves and issuers use extensions, so the raw taxonomy/concept
    pair is retained. Downstream research should use concept groups as mappings, not
    assume every issuer reports every concept under one canonical tag.
    """

    def normalize(
        self,
        *,
        symbol: str,
        payload: dict[str, Any],
        source_url: str,
        retrieved_at: datetime | None = None,
    ) -> list[FundamentalFact]:
        retrieved_at = retrieved_at or datetime.now(UTC)
        cik = str(payload.get("cik")) if payload.get("cik") is not None else None
        output: list[FundamentalFact] = []
        facts = payload.get("facts") or {}
        for taxonomy, concepts in facts.items():
            if not isinstance(concepts, dict):
                continue
            for concept, definition in concepts.items():
                if not isinstance(definition, dict):
                    continue
                label = str(definition.get("label") or concept)
                units = definition.get("units") or {}
                if not isinstance(units, dict):
                    continue
                for unit, observations in units.items():
                    if not isinstance(observations, list):
                        continue
                    for obs in observations:
                        if not isinstance(obs, dict):
                            continue
                        filed = obs.get("filed")
                        observed_at = retrieved_at
                        if isinstance(filed, str):
                            try:
                                observed_at = datetime.fromisoformat(filed).replace(tzinfo=UTC)
                            except ValueError:
                                pass
                        provenance = Provenance(
                            source=CorporateSource.SEC_COMPANYFACTS,
                            source_url=source_url,
                            retrieved_at=retrieved_at,
                            observed_at=observed_at,
                            accession_number=obs.get("accn"),
                            filing_form=obs.get("form"),
                        )
                        output.append(
                            FundamentalFact(
                                symbol=symbol.upper(),
                                cik=cik,
                                taxonomy=str(taxonomy),
                                concept=str(concept),
                                label=label,
                                value=obs.get("val"),
                                unit=str(unit),
                                period_start=obs.get("start"),
                                period_end=obs.get("end"),
                                fiscal_year=obs.get("fy"),
                                fiscal_period=obs.get("fp"),
                                form=obs.get("form"),
                                filed_at=filed,
                                frame=obs.get("frame"),
                                provenance=provenance,
                            )
                        )
        return output


class FilingDeltaDetector:
    """Point-in-time change detector for normalized corporate facts."""

    @staticmethod
    def latest_by_concept(facts: list[FundamentalFact]) -> dict[tuple[str, str, str | None], FundamentalFact]:
        latest: dict[tuple[str, str, str | None], FundamentalFact] = {}
        for fact in facts:
            key = (fact.taxonomy, fact.concept, fact.unit)
            incumbent = latest.get(key)
            if incumbent is None or (fact.filed_at or "") > (incumbent.filed_at or ""):
                latest[key] = fact
        return latest

    @staticmethod
    def numeric_change(current: FundamentalFact, previous: FundamentalFact) -> float | None:
        if not isinstance(current.value, (int, float)) or not isinstance(previous.value, (int, float)):
            return None
        if previous.value == 0:
            return None
        return (float(current.value) - float(previous.value)) / abs(float(previous.value))
