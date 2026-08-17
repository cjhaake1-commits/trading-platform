from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IBKRGlobalStatus:
    pillar: str = "ibkr_global"
    connection_status: str = "PENDING_SETUP"
    trading_enabled: bool = False
    scanning_enabled: bool = False
    reason: str = "IBKR paper credentials not configured"

    def as_dict(self) -> dict[str, object]:
        return {
            "pillar": self.pillar,
            "connection_status": self.connection_status,
            "trading_enabled": self.trading_enabled,
            "scanning_enabled": self.scanning_enabled,
            "reason": self.reason,
        }


class IBKRGlobalPaperAdapter:
    """Paper-only IBKR integration boundary.

    The fourth pillar is deliberately isolated from global preflight until an
    IBKR paper session is configured and explicitly enabled. No live-order path
    exists in this adapter.
    """

    def status(self) -> IBKRGlobalStatus:
        enabled = os.getenv("IBKR_PAPER_ENABLED", "").strip().lower() in {"1", "true", "yes"}
        host = os.getenv("IBKR_PAPER_HOST", "").strip()
        account = os.getenv("IBKR_PAPER_ACCOUNT_ID", "").strip()
        if not enabled or not host or not account:
            return IBKRGlobalStatus()
        return IBKRGlobalStatus(
            connection_status="CONFIGURED_NOT_VALIDATED",
            trading_enabled=False,
            scanning_enabled=False,
            reason="IBKR paper settings exist; connectivity and market data must be validated before enabling",
        )

    def open_positions(self) -> list[dict[str, object]]:
        status = self.status()
        if status.connection_status != "READY":
            return []
        raise RuntimeError("IBKR paper position retrieval is not enabled until connectivity validation is implemented")

    def submit_order(self, *args, **kwargs):
        raise RuntimeError("IBKR Global is paper-only and disabled until explicit connectivity validation")
