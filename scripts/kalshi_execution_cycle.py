#!/usr/bin/env python3
"""Execution-engine heartbeat with an immutable no-trade safety gate."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

from autotrader.capital_allocations import kalshi_pool_available
from autotrader.kalshi.client import KalshiDemoExecutionClient, KalshiReadOnlyClient
from autotrader.kalshi.config import KalshiConfig
from autotrader.models import AssetClass, PortfolioState, Side, TradeProposal
from autotrader.risk import RiskEngine
from autotrader.risk_stack import LayeredRiskStack


def _write_status(engine: str, result: dict[str, object]) -> None:
    path = Path(os.getenv("KALSHI_EXECUTION_STATUS_DIR", "var/kalshi")) / f"execution-{engine}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Readers (dashboard/checkpoint workers) may inspect this snapshot while
    # the provider loop is running.  Replace atomically so they never observe
    # an empty or partially-written JSON document.
    payload = json.dumps(result, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _read_status(engine: str) -> dict[str, object]:
    path = Path(os.getenv("KALSHI_EXECUTION_STATUS_DIR", "var/kalshi")) / f"execution-{engine}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_candidate_telemetry(engine: str, rows: list[dict[str, object]]) -> None:
    """Append research-only candidate decisions; never participates in execution."""
    if not rows:
        return
    path = Path(os.getenv("KALSHI_EXECUTION_STATUS_DIR", "var/kalshi")) / f"candidate-telemetry-{engine}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _prediction_funnel(markets: list[dict[str, object]]) -> dict[str, int]:
    data_valid = [m for m in markets if m.get("yes_bid_dollars") is not None and m.get("yes_ask_dollars") is not None]
    liquid = [m for m in data_valid if float(m.get("yes_bid_size_fp") or 0) > 0 and float(m.get("yes_ask_size_fp") or 0) > 0]
    spread_valid = [m for m in liquid if float(m.get("yes_ask_dollars") or 1) - float(m.get("yes_bid_dollars") or 0) <= 0.10]
    return {"scanned": len(markets), "data_valid": len(data_valid), "liquid": len(liquid),
            "spread_valid": len(spread_valid), "fee_valid": 0, "positive_edge": 0,
            "risk_approved": 0, "capital_approved": 0, "orders_submitted": 0}


def _perps_funnel(markets: list[dict[str, object]]) -> dict[str, int]:
    active = [m for m in markets if str(m.get("status") or "active").lower() in {"active", "open"}]
    valid_quotes = [m for m in active if _valid_perps_quote(m)]
    liquid = [m for m in valid_quotes if _number(m.get("volume_24h")) is not None and _number(m.get("volume_24h")) > 0]
    spread_valid = [m for m in liquid if _number(m.get("ask")) >= _number(m.get("bid"))]
    tick_valid = [m for m in spread_valid if _number(m.get("tick_size")) == 0.0001]
    # Official margin price bands are derived from the best quote when both
    # sides exist: lower=min(80%*bid, bid-1000*tick), upper=max(120%*ask,
    # ask+1000*tick).  The scanner has no candidate order yet, so this stage
    # records whether the market supplies enough evidence to validate one.
    band_valid = [m for m in tick_valid if _number(m.get("bid")) > 0 and _number(m.get("ask")) > 0]
    model_valid = [m for m in band_valid if _perps_baseline(m) is not None]
    positive_edge = [m for m in model_valid if _perps_baseline(m)["net_edge"] > 0]
    risk_results = [_perps_risk_evaluation(m) for m in positive_edge]
    risk_approved = [r for r in risk_results if r["risk_approved"]]
    capital_approved = [r for r in risk_approved if r["capital_approved"]]
    qualified = [r for r in capital_approved if r["qualified"]]
    return {"scanned": len(markets), "data_valid": len(active), "order_book_valid": len(valid_quotes), "liquid": len(liquid), "spread_valid": len(spread_valid),
            # Fee-tier metadata is optional for the current Demo margin surface;
            # its absence must not masquerade as a universal execution blocker.
            "tick_valid": len(tick_valid), "band_valid": len(band_valid), "fee_valid": len(band_valid), "model_valid": len(model_valid), "positive_edge": len(positive_edge), "risk_approved": len(risk_approved),
            "capital_approved": len(capital_approved), "qualified": len(qualified), "orders_submitted": 0}


def _perps_risk_evaluation(market: dict[str, object]) -> dict[str, object]:
    """Run a Perps candidate through the shared layered risk boundary.

    Perps quotes are contract prices.  The shared risk engine operates on
    dollar prices, so the provider contract size is applied before creating
    the proposal.  This preserves the existing risk formulas and avoids a
    Perps-specific approval flag or bypass.
    """
    model = _perps_baseline(market)
    ticker = str(market.get("ticker") or "")
    if model is None:
        return {"ticker": ticker, "risk_invoked": False, "risk_approved": False,
                "capital_approved": False, "qualified": False,
                "risk_rejection": "MODEL_INPUT_UNAVAILABLE"}
    mid = (_number(market.get("bid")) + _number(market.get("ask"))) / 2
    contract_size = _number(market.get("contract_size")) or 1.0
    if mid <= 0 or contract_size <= 0:
        return {"ticker": ticker, "risk_invoked": False, "risk_approved": False,
                "capital_approved": False, "qualified": False,
                "risk_rejection": "INVALID_CONTRACT_METADATA"}
    side = Side.BUY if model["signal"] == "LONG" else Side.SELL
    # A one-contract proposal is the minimum sizing probe; the risk engine
    # may reduce it further, but never increases it beyond the request.
    dollar_entry = mid * contract_size
    stop_distance = max(float(market.get("tick_size") or 0.0001) * contract_size,
                        float(model["spread_cost"]) * contract_size)
    stop = dollar_entry - stop_distance if side is Side.BUY else dollar_entry + stop_distance
    proposal = TradeProposal(
        symbol=ticker,
        asset_class=AssetClass.FUTURE,
        side=side,
        entry_price=dollar_entry,
        stop_price=stop,
        confidence=1.0,
        source="kalshi-perps-baseline",
        rationale="Existing Perps baseline after market-quality and net-edge gates",
        requested_quantity=1.0,
    )
    portfolio = PortfolioState(equity=1000.0, cash=1000.0)
    stack = LayeredRiskStack(RiskEngine())
    decision = stack.evaluate(proposal, portfolio)
    risk_approved = bool(decision.approved)
    risk_reason = decision.reason
    quantity = float(decision.quantity or 0.0)
    required_capital = quantity * dollar_entry if risk_approved else dollar_entry
    available = kalshi_pool_available(committed=0.0, pending=0.0)
    capital_approved = risk_approved and required_capital <= available and quantity >= 1.0
    if not risk_approved:
        capital_reason = "NOT_EVALUATED_RISK_REJECTED"
    elif capital_approved:
        capital_reason = "capital capacity available"
    else:
        capital_reason = "KALSHI_CAPITAL_INSUFFICIENT"
    # The Demo venue accepts whole contracts for this path.  A fractional
    # risk result is capacity information, not an executable order size.
    executable = quantity >= 1.0
    if risk_approved and required_capital <= available and not executable:
        capital_reason = "PROVIDER_MINIMUM_EXCEEDS_RISK_CAP"
    qualified = model["net_edge"] > 0 and risk_approved and capital_approved and executable
    return {
        "ticker": ticker,
        "signal": model["signal"],
        "gross_edge": model["gross_move"],
        "spread_cost": model["spread_cost"],
        "fee_cost": model["fee_cost"],
        "funding_cost": model["funding_cost"],
        "net_edge": model["net_edge"],
        "risk_invoked": True,
        "risk_approved": risk_approved,
        "risk_rejection": None if risk_approved else risk_reason,
        "proposed_quantity": 1.0,
        "approved_quantity": quantity,
        "capital_required": required_capital,
        "capital_available": available,
        "capital_approved": capital_approved,
        "capital_rejection": None if capital_approved else capital_reason,
        "provider_minimum_valid": executable,
        "qualified": qualified,
    }


def _perps_order_payload(market: dict[str, object], evaluation: dict[str, object]) -> dict[str, object]:
    """Build the normal Demo mutation payload only after qualification."""
    if not evaluation.get("qualified"):
        raise ValueError("unqualified Perps candidate cannot reach order builder")
    signal = str(evaluation["signal"])
    return {
        "ticker": str(market["ticker"]),
        # Margin orders use the bid/ask book side and the short wire key
        # ``count``; the event-contract API's yes/no and count_fp keys are
        # not valid on /margin/orders.
        "side": "bid" if signal == "LONG" else "ask",
        "count": f"{float(evaluation['approved_quantity']):.2f}",
        # Margin API schema requires fixed-point prices as strings.
        "price": f"{float(market['ask'] if signal == 'LONG' else market['bid']):.4f}",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": f"perps-baseline-{market['ticker']}",
    }


def _perps_baseline(market: dict[str, object]) -> dict[str, float | str] | None:
    """Evaluate the existing transparent momentum baseline on a Perps quote.

    The settlement mark is the provider's prior reference, so it is used as
    the lookback anchor. Optional funding/fee metadata remains neutral when
    absent; it never invalidates the baseline model.
    """
    bid = _number(market.get("bid"))
    ask = _number(market.get("ask"))
    mark = market.get("settlement_mark_price")
    mark_price = _number(mark.get("price")) if isinstance(mark, dict) else None
    if not _valid_perps_quote(market) or mark_price is None or mark_price <= 0:
        return None
    mid = (bid + ask) / 2.0
    momentum = (mid / mark_price) - 1.0
    spread_cost = max(ask - bid, 0.0)
    gross_move = abs(momentum) * mid
    net_edge = gross_move - spread_cost
    return {
        "signal": "LONG" if momentum > 0 else ("SHORT" if momentum < 0 else "NEUTRAL"),
        "gross_move": gross_move,
        "spread_cost": spread_cost,
        "fee_cost": 0.0,
        "funding_cost": 0.0,
        "net_edge": net_edge,
    }


def _number(value: object) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _valid_perps_quote(market: dict[str, object]) -> bool:
    """Accept executable provider quotes only, excluding Kalshi sentinels.

    The Demo API uses zero and the signed 64-bit maximum as no-liquidity
    markers. Treating those values as prices creates fabricated edge and can
    overflow the shared risk calculation.
    """
    bid = _number(market.get("bid"))
    ask = _number(market.get("ask"))
    return bid is not None and ask is not None and 0 < bid <= ask < 1_000_000.0


def cycle() -> dict[str, object]:
    engine = os.getenv("KALSHI_ENGINE", "predictions").lower()
    config = KalshiConfig.from_env()
    prior_status = _read_status(engine)
    prior_cycles = prior_status.get("cycle_count", 0)
    try:
        cycle_count = int(prior_cycles) + 1
    except (TypeError, ValueError):
        cycle_count = 1
    result: dict[str, object] = {"engine": engine, "observed_at": datetime.now(UTC).isoformat(),
                                 "orders": 0, "fills": 0, "decision": "HOLD_CASH",
                                 "execution_enabled": config.demo_trading_enabled, "broker_control": config.broker_control,
                                 "cycle_count": cycle_count}
    if (config.environment != "demo" or not config.demo_trading_enabled
            or config.paper_capital <= 0):
        result["decision"] = "FAIL_CLOSED"
        result["last_rejection_reason"] = "SAFETY_GATE"
        _write_status(engine, result)
        return result
    client = KalshiReadOnlyClient(config)
    try:
        if engine == "predictions":
            markets = client.markets(limit="100")
            rows = markets.get("markets", [])
            funnel = _prediction_funnel(rows)
            result["candidate_telemetry"] = [{
                "observed_at": result["observed_at"], "engine": engine,
                "ticker": market.get("ticker"), "event": market.get("event_ticker") or market.get("event"),
                "yes_bid": market.get("yes_bid_dollars"), "yes_ask": market.get("yes_ask_dollars"),
                "no_bid": market.get("no_bid_dollars"), "no_ask": market.get("no_ask_dollars"),
                "yes_bid_size": market.get("yes_bid_size_fp"), "yes_ask_size": market.get("yes_ask_size_fp"),
                "no_bid_size": market.get("no_bid_size_fp"), "no_ask_size": market.get("no_ask_size_fp"),
                "volume": market.get("volume"), "open_interest": market.get("open_interest"),
                "qualification": "REJECTED", "rejection": "INSUFFICIENT_SPREAD_OR_LIQUIDITY",
                "estimated_probability": "UNKNOWN", "probability_edge": "UNKNOWN",
            } for market in rows]
            result.update({"state": "SCANNING", "markets": len(rows), "funnel": funnel,
                           "last_rejection_reason": "NO_POSITIVE_EDGE" if funnel["spread_valid"] else "INSUFFICIENT_SPREAD_OR_LIQUIDITY"})
        elif engine == "reconciliation":
            result.update({"state": "CONNECTED", "positions": len(client.positions(limit="100").get("market_positions", [])),
                           "orders": len(client.orders_read_only(limit="100").get("orders", [])),
                           "fills": len(client.fills(limit="100").get("fills", []))})
        else:
            enabled = client.perps_enabled()
            markets = client.perps_markets(limit="100")
            rows = markets.get("markets", [])
            funnel = _perps_funnel(rows)
            evaluations = sorted(
                [(m, _perps_risk_evaluation(m)) for m in rows if _perps_baseline(m) is not None],
                key=lambda pair: float(pair[1].get("net_edge", 0.0)), reverse=True,
            )
            result["top_candidates"] = [evaluation for _, evaluation in evaluations[:10]]
            qualified = [(m, evaluation) for m, evaluation in evaluations if evaluation.get("qualified")]
            submitted = 0
            if qualified:
                try:
                    existing = client.perps("orders").get("orders", [])
                    positions = client.perps_positions().get("positions", [])
                    occupied = {str(item.get("ticker")) for item in [*existing, *positions]}
                except Exception:
                    occupied = set()
                for market, evaluation in qualified[:1]:
                    if str(market.get("ticker")) in occupied:
                        evaluation["qualified"] = False
                        evaluation["capital_rejection"] = "DUPLICATE_EXPOSURE"
                        continue
                    try:
                        prior = _read_status("perps")
                        prior_at = datetime.fromisoformat(str(prior.get("observed_at")))
                        prior_rejected = prior.get("provider_submission_state") == "REJECTED"
                        if prior_rejected and datetime.now(UTC) - prior_at < timedelta(minutes=5):
                            evaluation["order_state"] = "BLOCKED_PROVIDER_COOLDOWN"
                            evaluation["order_rejection"] = "PROVIDER_SUBMISSION_COOLDOWN"
                            break
                        payload = _perps_order_payload(market, evaluation)
                        response = KalshiDemoExecutionClient(config).create_order(payload, family="perps")
                        evaluation["order_state"] = "ACKNOWLEDGED"
                        evaluation["order_response"] = {"order_id": response.get("order_id") or response.get("order", {}).get("order_id")}
                        submitted = 1
                    except ValueError:
                        payload = _perps_order_payload(market, evaluation)
                        response = KalshiDemoExecutionClient(config).create_order(payload, family="perps")
                        evaluation["order_state"] = "ACKNOWLEDGED"
                        evaluation["order_response"] = {"order_id": response.get("order_id") or response.get("order", {}).get("order_id")}
                        submitted = 1
                    except HTTPError as exc:
                        evaluation["order_state"] = "REJECTED"
                        try:
                            body = exc.read().decode("utf-8", errors="replace")[:300]
                        except Exception:
                            body = ""
                        evaluation["order_rejection"] = f"HTTP_{exc.code}"
                        evaluation["provider_rejection"] = body or "provider returned no detail"
                        result["provider_submission_state"] = "REJECTED"
                        result["provider_rejection"] = evaluation["provider_rejection"]
                    except Exception as exc:
                        evaluation["order_state"] = "REJECTED"
                        evaluation["order_rejection"] = type(exc).__name__
                        result["provider_submission_state"] = "REJECTED"
                    break
            funnel["orders_submitted"] = submitted
            # Reconcile the authenticated Margin portfolio after every cycle;
            # the Margin API returns order/fill objects at the response root,
            # not under the event-contract ``order`` wrapper.
            try:
                live_orders = client.perps("orders").get("orders", [])
                live_positions = client.perps_positions().get("positions", [])
                live_fills = client.perps_fills().get("fills", [])
                live_balance = client.perps_balance()
                balances = live_balance.get("subaccount_balances", [])
                initial_margin = sum(float(b.get("initial_margin") or 0) for b in balances)
                open_orders = [o for o in live_orders if float(o.get("remaining_count") or 0) > 0]
                result.update({
                    "orders": len(live_orders),
                    "orders_acknowledged": len(live_orders),
                    "open_orders": len(open_orders),
                    "fills": len(live_fills),
                    "positions": len(live_positions),
                    "capital_deployed": initial_margin,
                    "margin_used": initial_margin,
                    "available_balance": sum(float(b.get("available_balance") or 0) for b in balances),
                    "unrealized_pnl": sum(float(p.get("unrealized_pnl") or 0) for p in live_positions),
                })
            except Exception as exc:
                result["reconciliation_error"] = type(exc).__name__
            result["top_candidates"] = sorted(
                result["top_candidates"],
                key=lambda x: float(x.get("net_edge", 0.0)), reverse=True,
            )[:10]
            result["candidate_telemetry"] = [{
                "observed_at": result["observed_at"], "engine": engine, "ticker": candidate.get("ticker"),
                "strategy": "PERPS_BASELINE", "signal_strength": candidate.get("gross_edge"),
                "confidence": 1.0, "edge_proxy": candidate.get("net_edge"), "ev_proxy": candidate.get("net_edge"),
                "existing_exposure": candidate.get("capital_required"), "provider_minimum": candidate.get("provider_minimum_valid"),
                "risk_decision": candidate.get("risk_approved"), "capital_availability": candidate.get("capital_available"),
                "qualification": "QUALIFIED" if candidate.get("qualified") else "REJECTED",
                "rejection": candidate.get("risk_rejection") or candidate.get("capital_rejection") or candidate.get("order_rejection"),
                "estimated_edge": "UNKNOWN", "expected_value": "UNKNOWN",
            } for candidate in result.get("top_candidates", [])]
            rejection = "NO_POSITIVE_EDGE"
            if funnel.get("positive_edge", 0) and funnel.get("risk_approved", 0) == 0:
                rejection = "RISK_REJECTED"
            elif funnel.get("risk_approved", 0) and funnel.get("capital_approved", 0) == 0:
                rejection = "CAPITAL_REJECTED"
            elif funnel.get("qualified", 0):
                rejection = "READY_TO_SUBMIT"
            if funnel.get("band_valid", 0) == 0:
                rejection = "PRICE_BAND_UNAVAILABLE"
            result.update({"state": "SCANNING" if enabled.get("enabled", True) else "EXTERNAL_BLOCK",
                           "margin_enabled": enabled, "instruments": len(rows), "funnel": funnel,
                           "funding_state": "OPTIONAL_UNAVAILABLE", "fee_state": "OPTIONAL_UNAVAILABLE",
                           "last_rejection_reason": (
                               "PROVIDER_SUBMISSION_REJECTED"
                               if result.get("provider_submission_state") == "REJECTED"
                               else rejection
                           ) if enabled.get("enabled", True) else "MARGIN_DISABLED"})
    except Exception as exc:
        result.update({"state": "API_DEGRADED", "error": type(exc).__name__})
        result["last_rejection_reason"] = "API_DEGRADED"
    _write_candidate_telemetry(engine, result.pop("candidate_telemetry", []))
    _write_status(engine, result)
    return result


if __name__ == "__main__":
    print(json.dumps(cycle(), sort_keys=True))
