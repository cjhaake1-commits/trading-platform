from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from .audit import SQLiteAuditStore
from .coordinated_dry_run import DryRunDecision
from .models import AuditEvent

ADAPTER_BOUNDARIES = {
    "alpaca-paper": "Alpaca PAPER protected-order adapter",
    "alpaca-crypto-paper": "Alpaca PAPER crypto adapter",
    "alpaca-metals-paper": "Alpaca PAPER metals adapter",
    "oanda-practice": "OANDA Practice protected-order adapter",
    "saxo-sim": "Saxo SIM protected-order adapter",
}


def preview_execution_pipeline(
    decisions: list[DryRunDecision],
    *,
    audit: SQLiteAuditStore,
    now: datetime | None = None,
) -> dict[str, object]:
    """Advance decisions to the adapter boundary without importing submit callables."""

    timestamp = now or datetime.now(UTC)
    rows = []
    for decision in decisions:
        approved = decision.risk_engine_status == "approved"
        record = {
            "decision": asdict(decision),
            "stages": {
                "signal": "recorded",
                "proposal": "recorded",
                "deterministic_risk_engine": decision.risk_engine_status,
                "broker_adapter": "ready_at_submission_boundary" if approved else "not_reached",
                "trade_logger": "proposal_logged",
                "cash_accounting": "previewed_no_cash_mutation",
                "learning_history": "awaiting_completed_trade" if approved else "rejection_available_for_evaluation",
                "streamlit_dashboard": "preview_payload_ready",
            },
            "adapter_boundary": ADAPTER_BOUNDARIES.get(decision.broker, "unsupported broker adapter"),
            "submission_invoked": False,
        }
        audit.append(
            AuditEvent(
                "paper_order_pipeline_preview",
                "Paper proposal reached no-submit execution preview",
                record,
                created_at=timestamp,
            )
        )
        rows.append(record)
    return {
        "generated_at": timestamp.astimezone(UTC).isoformat(),
        "orders_submitted": 0,
        "submission_boundary_enforced": True,
        "items": rows,
    }
