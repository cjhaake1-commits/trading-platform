"""Canonical operator-facing pillar/provider identities.

Legacy database keys remain stable for compatibility; they are not execution
provider names shown to operators.
"""
from __future__ import annotations

INTERNATIONAL_IDENTITY = {
    "pillar": "International",
    "execution_provider": "Saxo SIM",
    "current_fund": "paper-fund",
    "current_epoch": "international-current-fund-v1",
    "legacy_epoch": "international-legacy-pre-v1",
    "legacy_internal_key": "ibkr_global",
}


def canonical_identity(pillar: str, internal_key: str | None = None) -> dict[str, str]:
    if pillar == "International" or internal_key == INTERNATIONAL_IDENTITY["legacy_internal_key"]:
        return INTERNATIONAL_IDENTITY.copy()
    return {"pillar": pillar, "execution_provider": "UNKNOWN", "current_fund": "paper-fund"}


__all__ = ["INTERNATIONAL_IDENTITY", "canonical_identity"]
