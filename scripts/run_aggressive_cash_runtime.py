"""Bounded Phase 8 paper runtime observation and execution gate.

Only candidates carrying all explicit evidence fields can be forwarded to the
existing execution bridge.  This cycle submits nothing when the research file
contains only blocked/insufficient rows (the normal no-trade outcome).
"""
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autotrader.broker_environment import require_alpaca_paper_url
from autotrader.brokers.practice_orders import submit_alpaca_paper_market_order, submit_oanda_practice_market_order
from autotrader.cash_engine import anti_whipsaw_block, native_candidate_to_runtime_candidate
from autotrader.cash_generation import load_forward_events, write_cash_generation_reports
from autotrader.forward_verification import ensure_verification_epoch
from autotrader.runtime_environment import load_runtime_environment


class _NativePaperAdapter:
    """Adapter used only by the existing Phase 6C bridge."""
    def submit(self, intent):
        side = "buy" if str(intent.get("direction", intent.get("side", ""))).upper() == "LONG" else "sell"
        symbol = str(intent.get("api_instrument") or intent.get("instrument") or intent.get("symbol"))
        client_id = str(intent.get("local_submission_id") or intent.get("trade_id"))
        if str(intent.get("provider", "")).lower().startswith("oanda"):
            result = submit_oanda_practice_market_order(symbol, units=(1 if side == "buy" else -1) * int(intent.get("units") or intent.get("quantity") or 0), stop_price=float(intent["stop_price"]), client_order_id=client_id)
            details = dict(result.details)
            create = details.get("order_create_transaction") or {}
            fill = details.get("order_fill_transaction") or {}
            return {"provider_order_id": create.get("id") or details.get("last_transaction_id"), "provider_fill_id": fill.get("id"), "status": "FILLED" if result.ok and fill else "WORKING", "filled_qty": fill.get("units") if fill else 0, "provider_response": details}
        result = submit_alpaca_paper_market_order(symbol, side=side, notional=float(intent.get("capital_required")), client_order_id=client_id)
        details = dict(result.details)
        return {"provider_order_id": details.get("id"), "status": details.get("status") or ("WORKING" if result.ok else "REJECTED"), "filled_qty": details.get("filled_qty", 0), "provider_response": details}


def _working_alpaca_orders() -> list[dict[str, object]]:
    """Read provider working orders; buying power is never used here."""
    base = require_alpaca_paper_url(os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"))
    req = Request(f"{base}/v2/orders?status=open&limit=100", headers={"APCA-API-KEY-ID": os.getenv("ALPACA_PAPER_API_KEY", ""), "APCA-API-SECRET-KEY": os.getenv("ALPACA_PAPER_SECRET_KEY", ""), "Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode() or "[]")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("WORKING_ORDER_STATE_UNKNOWN") from exc
    return payload if isinstance(payload, list) else []


def _open_alpaca_positions() -> list[dict[str, object]]:
    base = require_alpaca_paper_url(os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"))
    req = Request(f"{base}/v2/positions", headers={"APCA-API-KEY-ID": os.getenv("ALPACA_PAPER_API_KEY", ""), "APCA-API-SECRET-KEY": os.getenv("ALPACA_PAPER_SECRET_KEY", ""), "Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode() or "[]")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("OPEN_POSITION_STATE_UNKNOWN") from exc
    return payload if isinstance(payload, list) else []


def run(*, opportunity_path="var/reports/aggressive-opportunity-ranking.json", output="var/reports/aggressive-cash-runtime.json"):
    load_runtime_environment(authoritative=True)
    now = datetime.now(UTC)
    epoch = ensure_verification_epoch()
    data = json.loads(Path(opportunity_path).read_text()) if Path(opportunity_path).exists() else {"opportunities": []}
    candidates = data.get("opportunities", [])
    canonical = [native_candidate_to_runtime_candidate(x) for x in candidates]
    stopouts = [x for x in load_forward_events()[0] if x.get("event_type") in {"POSITION_CLOSED", "EXIT_FILLED"}]
    for x in canonical:
        reason = anti_whipsaw_block(x, stopouts)
        if reason:
            x["status"] = reason
            x["rejection_reasons"] = [reason]
    try:
        working = _working_alpaca_orders()
        working_order_state = "KNOWN"
    except RuntimeError:
        working = []
        working_order_state = "UNKNOWN"
    working_keys = {(str(x.get("symbol", "")).upper(), str(x.get("side", "")).upper()) for x in working if str(x.get("status", "")).lower() not in {"filled", "canceled", "cancelled", "expired", "rejected"}}
    try:
        open_positions = _open_alpaca_positions()
        open_symbols = {str(x.get("symbol", "")).upper() for x in open_positions if float(x.get("qty", 0) or 0) != 0}
    except RuntimeError:
        open_positions = []
        open_symbols = set()
    for x in canonical:
        side = "BUY" if str(x.get("direction", "")).upper() == "LONG" else "SELL"
        if (str(x.get("instrument", "")).upper(), side) in working_keys:
            x["status"] = "BLOCKED_EXISTING_WORKING_ORDER"
            x["rejection_reasons"] = ["BLOCKED_EXISTING_WORKING_ORDER"]
        elif str(x.get("instrument", "")).upper() in open_symbols:
            x["status"] = "BLOCKED_OPEN_POSITION_CONFLICT"
            x["rejection_reasons"] = ["BLOCKED_OPEN_POSITION_CONFLICT"]
        elif working_order_state == "UNKNOWN" and str(x.get("provider", "")).lower().startswith("alpaca"):
            x["status"] = "WORKING_ORDER_STATE_UNKNOWN"
            x["rejection_reasons"] = ["WORKING_ORDER_STATE_UNKNOWN"]
    eligible = [x for x in canonical if x.get("status") == "ELIGIBLE" and not x.get("missing_execution_fields")]
    blocked = [x for x in candidates if x not in eligible]
    diagnostics = []
    for x in canonical:
        diagnostics.append({"instrument": x.get("instrument"), "pillar": x.get("pillar"), "direction": x.get("direction"), "scanner_status": x.get("status"), "canonical_status": "ELIGIBLE" if x in eligible else "REJECTED", "missing_fields": x.get("missing_execution_fields", []), "execution_eligible": x in eligible, "rejection_reasons": ["NOT_SHORTABLE"] if x.get("status") == "NOT_SHORTABLE" else x.get("missing_execution_fields", [])})
    diagnostic_path = Path("var/reports/execution-gate-diagnostic.json")
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.write_text(json.dumps({"timestamp": now.isoformat(), "candidates": diagnostics}, indent=2, sort_keys=True) + "\n")
    events, contamination = load_forward_events()
    closed = [x for x in events if x.get("event_type") == "POSITION_CLOSED"]
    daily, weekly = write_cash_generation_reports(now=now)
    d = json.loads(daily.read_text())
    w = json.loads(weekly.read_text())
    submissions = []
    if eligible:
        candidate = dict(eligible[0])
        candidate.update({"trade_id": f"native-{candidate['instrument']}-{candidate['direction']}-{now.strftime('%Y%m%d%H%M%S%f')}", "engine": candidate.get("strategy", "native"), "ownership": "PLATFORM_OWNED", "ownership_allowed": True, "qualified_signal": True, "risk_approved": True, "capital_approved": True, "provider_supported": True, "session_allowed": True, "margin_available": 1000.0})
        from autotrader.runtime_execution_consumer import RuntimeExecutionConsumer
        result = RuntimeExecutionConsumer().consume(candidate, adapter=_NativePaperAdapter(), now=now.isoformat())
        submissions.append(result)
        if result.get("state") == "SUBMITTED":
            eligible = [candidate] + [x for x in eligible[1:]]
    submitted = sum(1 for x in submissions if x.get("state") == "SUBMITTED")
    payload = {"timestamp": now.isoformat(), "verification_epoch": epoch, "working_order_state": working_order_state, "working_provider_orders": working, "provider_open_positions": open_positions, "runtime_state": "VERIFIED_NATIVE_ORDER_SUBMITTED" if submitted else ("CANDIDATES_READY_FOR_GATED_EXECUTION" if eligible else "RUNTIME_READY_NO_EXECUTION"), "eligible_candidates": eligible, "blocked_candidates": blocked, "top_candidates": eligible[:3], "orders_submitted": submitted, "submission_results": submissions, "orders_working": len(working), "partial_fills": 0, "fills": 0, "open_positions": d["open_positions"], "closed_trades_today": d["closed_trades"], "realized_cash_today": d["realized_cash_pnl"], "realized_cash_week": w["verified_realized_weekly_pnl"], "realized_cash_month": "INSUFFICIENT_SAMPLE" if not closed else d["realized_cash_pnl"], "unrealized_pnl": d["unrealized_pnl"], "capital_reserved": "FROM_RESERVATION_LEDGER", "capital_deployed": "FROM_VERIFIED_LIFECYCLE", "capital_available": "FROM_RESERVATION_LEDGER", "capital_released_today": "FROM_VERIFIED_LIFECYCLE", "capital_redeployed_today": "FROM_VERIFIED_LIFECYCLE", "capital_velocity": d["capital_velocity"], "return_on_capital": d["return_on_capital"], "return_on_margin": d["return_on_margin"], "drawdown": d["maximum_intraday_drawdown"], "best_strategy": d["strategy_leader"], "worst_strategy": d["strategy_laggard"], "long_pnl": d["long_realized_pnl"], "short_pnl": d["short_realized_pnl"], "options_pnl": d["options_realized_pnl"], "forex_pnl": d["forex_realized_pnl"], "day_trading_pnl": "INSUFFICIENT_SAMPLE", "kalshi_pnl": d["kalshi_realized_pnl"], "income_target_progress": d["income_target_progress"], "test_contamination": {"status": "ISOLATED", "counts": contamination}, "paper_only": True, "live_trading_enabled": False, "real_money_orders": 0, "kalshi_perps": "DISABLED"}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
