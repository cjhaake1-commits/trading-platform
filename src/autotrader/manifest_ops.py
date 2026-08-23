"""Evidence-based manifest observability and archival primitives.

Archiving is append-only: the original entry manifest remains immutable and
the archive record records why it left the operational view.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable


class ManifestCategory(StrEnum):
    ARCHIVABLE_HISTORICAL = "ARCHIVABLE_HISTORICAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    LEGITIMATE_ACTIVE = "LEGITIMATE_ACTIVE"
    AWAITING_EXTERNAL_EVIDENCE = "AWAITING_EXTERNAL_EVIDENCE"
    CORRUPT = "CORRUPT"
    SOFTWARE_DEFECT = "SOFTWARE_DEFECT"


@dataclass(frozen=True)
class ManifestDisposition:
    manifest_id: str
    category: ManifestCategory
    reason: str
    evidence: tuple[str, ...] = ()


TERMINAL = {"filled_closed", "cancelled_unfilled", "reconciled", "rejected", "closed"}


def classify_manifest(
    manifest: dict[str, object],
    *,
    experiment_start: datetime | None,
    open_order_ids: Iterable[str] = (),
    position_symbols: Iterable[str] = (),
) -> ManifestDisposition:
    mid = str(manifest.get("manifest_id") or "")
    state = str(manifest.get("lifecycle_state") or "").lower()
    symbol = str(manifest.get("canonical_symbol") or "").upper()
    order_id = str(manifest.get("broker_order_id") or "")
    if not mid or not symbol:
        return ManifestDisposition(mid, ManifestCategory.CORRUPT, "missing manifest identity or symbol")
    if state in {"filled", "filled_closed", "reconciled", "closed"}:
        return ManifestDisposition(mid, ManifestCategory.COMPLETED, "terminal ledger lifecycle")
    if state in {"cancelled_unfilled", "rejected"}:
        return ManifestDisposition(mid, ManifestCategory.CANCELLED, "terminal zero-fill/rejected lifecycle")
    created = manifest.get("created_at")
    current_position = symbol in {str(x).upper() for x in position_symbols}
    current_experiment = False
    if experiment_start is not None and isinstance(created := manifest.get("created_at"), str):
        try:
            current_experiment = datetime.fromisoformat(created.replace("Z", "+00:00")) >= experiment_start
        except ValueError:
            current_experiment = False
    if order_id in set(open_order_ids) or (current_position and current_experiment):
        return ManifestDisposition(mid, ManifestCategory.LEGITIMATE_ACTIVE, "current broker order or position evidence")
    if experiment_start is not None and isinstance(created, str):
        try:
            observed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if observed >= experiment_start:
                return ManifestDisposition(mid, ManifestCategory.AWAITING_EXTERNAL_EVIDENCE, "current experiment record lacks conclusive broker evidence")
        except ValueError:
            return ManifestDisposition(mid, ManifestCategory.CORRUPT, "invalid created_at timestamp")
    if state in {"reconciliation_deferred", "manual_review_required"}:
        return ManifestDisposition(mid, ManifestCategory.ARCHIVABLE_HISTORICAL, "pre-experiment deferred record with no current broker evidence")
    return ManifestDisposition(mid, ManifestCategory.AWAITING_EXTERNAL_EVIDENCE, "non-terminal state lacks conclusive external evidence")
