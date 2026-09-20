"""Provider-native, read-only probes and bounded candidate discovery.

Network errors are isolated per provider.  This module never falls back to
public data for an executable candidate.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .broker_environment import require_alpaca_paper_url, require_oanda_practice_url
from .cash_engine import validate_native_quote
from .provider_scanners import EQUITIES, FOREX, METALS
from .runtime_environment import load_runtime_environment


def _get(url: str, headers: dict[str, str], timeout: float = 5) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def _health(name: str, url: str, headers: dict[str, str]) -> dict[str, object]:
    try:
        payload = _get(url, headers)
        return {"status": "OK", "endpoint": url.split("?", 1)[0], "evidence": "HTTP response", "payload_keys": sorted(payload)[:12]}
    except HTTPError as exc:
        return {"status": "AUTH_REQUIRED" if exc.code in {401, 403} else "HTTP_FAILURE", "endpoint": url.split("?", 1)[0], "http_status": exc.code}
    except (URLError, OSError, ValueError) as exc:
        return {"status": "UNREACHABLE", "endpoint": url.split("?", 1)[0], "reason": type(exc).__name__}


def native_provider_health() -> dict[str, object]:
    environment = load_runtime_environment(authoritative=True)
    alpaca_base = require_alpaca_paper_url(os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"))
    alpaca_data = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/")
    oanda_base = require_oanda_practice_url(os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com"))
    ak, ask = os.getenv("ALPACA_PAPER_API_KEY", ""), os.getenv("ALPACA_PAPER_SECRET_KEY", "")
    ot = os.getenv("OANDA_PRACTICE_TOKEN", "")
    health = {"generated_at": datetime.now(UTC).isoformat(), "env_loaded_from": environment, "dns": "NOT_PROBED", "https": "NOT_PROBED", "alpaca_trading": {"status": "CREDENTIALS_MISSING"}, "alpaca_data": {"status": "CREDENTIALS_MISSING"}, "alpaca_options": {"status": "PROVIDER_PROBE_REQUIRED"}, "oanda_practice": {"status": "CREDENTIALS_MISSING"}, "kalshi_demo": {"status": "READ_ONLY_PROBE_REQUIRED"}, "saxo_sim": {"status": "AUTH_REQUIRED"}, "yahoo_research": {"status": "RESEARCH_ONLY"}, "paper_only": True, "live_trading_enabled": False}
    if ak and ask:
        headers = {"APCA-API-KEY-ID": ak, "APCA-API-SECRET-KEY": ask, "Accept": "application/json"}
        health["alpaca_trading"] = _health("alpaca", f"{alpaca_base}/v2/account", headers)
        health["alpaca_data"] = _health("alpaca", f"{alpaca_data}/v2/stocks/SPY/quotes/latest", headers)
        health["alpaca_options"] = _health("alpaca", f"{alpaca_data}/v1beta1/options/snapshots/SPY", headers)
    if ot:
        health["oanda_practice"] = _health("oanda", f"{oanda_base}/v3/accounts", {"Authorization": f"Bearer {ot}", "Accept": "application/json"})
    try:
        from .kalshi.client import KalshiReadOnlyClient
        from .kalshi.config import KalshiConfig
        markets = KalshiReadOnlyClient(KalshiConfig.from_env(), timeout=5, max_retries=0).markets(limit="10")
        health["kalshi_demo"] = {"status": "OK_READ_ONLY", "markets_observed": len(markets.get("markets", [])) if isinstance(markets, dict) else 0}
    except Exception as exc:  # provider-isolated diagnostic; no secret-bearing exception text
        health["kalshi_demo"] = {"status": "UNREACHABLE", "reason": type(exc).__name__}
    statuses = [health[name].get("status") for name in ("alpaca_trading", "alpaca_data", "oanda_practice", "kalshi_demo") if isinstance(health.get(name), dict)]
    health["dns"] = "OK" if any(status in {"OK", "OK_READ_ONLY", "AUTH_REQUIRED"} for status in statuses) else "UNVERIFIED"
    health["https"] = "OK" if any(status in {"OK", "OK_READ_ONLY", "AUTH_REQUIRED", "HTTP_FAILURE"} for status in statuses) else "UNVERIFIED"
    return health


def scan_all_native_providers(*, output: str | Path = "var/reports/aggressive-opportunity-ranking.json") -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return only candidates backed by successful native endpoints."""
    health = native_provider_health()
    rows: list[dict[str, object]] = []
    alpaca_base = require_alpaca_paper_url(os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"))
    alpaca_data = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/")
    headers = {"APCA-API-KEY-ID": os.getenv("ALPACA_PAPER_API_KEY", ""), "APCA-API-SECRET-KEY": os.getenv("ALPACA_PAPER_SECRET_KEY", ""), "Accept": "application/json"}
    for symbol in EQUITIES + METALS:
        if health["alpaca_data"].get("status") == "OK":
            try:
                quote = _get(f"{alpaca_data}/v2/stocks/{symbol}/quotes/latest", headers)
                asset = _get(f"{alpaca_base}/v2/assets/{symbol}", headers)
                query = urlencode({"timeframe": "1Hour", "limit": "50"})
                bars = _get(f"{alpaca_data}/v2/stocks/{symbol}/bars?{query}", headers | {"Accept": "application/json"})
                rows.extend(_quote_rows(symbol, "stocks" if symbol in EQUITIES else "metals", quote, "alpaca-paper", asset=asset, bars=bars))
            except Exception as exc:
                reason = f"HTTP_{exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
                rows.extend(_blocked(symbol, "stocks" if symbol in EQUITIES else "metals", "alpaca-paper", reason, health["alpaca_data"]))
        else:
            rows.extend(_blocked(symbol, "stocks" if symbol in EQUITIES else "metals", "alpaca-paper", "NATIVE_ALPACA_UNAVAILABLE", health["alpaca_data"]))
    for symbol in FOREX:
        rows.extend(_oanda_rows(symbol, health["oanda_practice"]))
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "paper_only": True, "provider_health": health, "opportunities": rows}, indent=2, sort_keys=True) + "\n")
    return rows, health


def _quote_rows(symbol: str, pillar: str, payload: dict, provider: str, *, asset: dict | None = None, bars: dict | None = None) -> list[dict[str, object]]:
    quote = payload.get("quote", payload) if isinstance(payload, dict) else {}
    bid, ask = quote.get("bp"), quote.get("ap")
    spread = float(ask) - float(bid) if bid is not None and ask is not None else None
    quote_valid, validated_spread, quote_error = validate_native_quote(bid, ask)
    if quote_valid:
        spread = validated_spread
    observed = quote.get("t")
    values = [float(x.get("c")) for x in (bars or {}).get("bars", []) if x.get("c") is not None]
    change = (values[-1] - values[-5]) / values[-5] if len(values) >= 5 else None
    atr = sum(abs(values[i] - values[i - 1]) for i in range(1, len(values[-15:]))) / max(len(values[-15:]) - 1, 1) if len(values) >= 2 else None
    shortable = bool((asset or {}).get("shortable"))
    rows = []
    for direction in ("LONG", "SHORT"):
        aligned = change is not None and ((change > 0 and direction == "LONG") or (change < 0 and direction == "SHORT"))
        stop_distance = max(atr or 0, (spread or 0) * 2)
        entry = (float(ask) if direction == "LONG" and quote_valid else float(bid) if direction == "SHORT" and quote_valid else None)
        quantity = min(int(12.5 / stop_distance), int(1000 / entry)) if stop_distance and entry else 0
        risk = stop_distance * quantity if quantity else None
        stop_price = entry - stop_distance if entry and direction == "LONG" else entry + stop_distance if entry else None
        target_distance = stop_distance * 1.5 if stop_distance else None
        target_price = entry + target_distance if entry and direction == "LONG" else entry - target_distance if entry else None
        expected_cost = spread * quantity if quote_valid and spread is not None else None
        expected_gross = target_distance * quantity if aligned and target_distance and quantity else None
        expected_net = expected_gross - expected_cost if expected_gross is not None and expected_cost is not None else None
        model_edge = expected_net / max(entry * quantity, 1e-9) if expected_net is not None else None
        model_return = expected_net if expected_net is not None else None
        status = quote_error or ("NOT_SHORTABLE" if direction == "SHORT" and not shortable else "INSUFFICIENT_EDGE")
        if quote_valid and aligned and quantity > 0 and expected_net is not None and expected_net > 0 and bool((asset or {}).get("tradable")) and (direction != "SHORT" or shortable):
            status = "ELIGIBLE"
        rows.append({"pillar": pillar, "provider": provider, "provider_environment": "PAPER", "instrument": symbol, "direction": direction, "strategy": "MOMENTUM", "status": status, "data_source": "ALPACA_NATIVE_QUOTE_BARS", "observed_at": datetime.now(UTC).isoformat(), "provider_timestamp": observed, "freshness": "FRESH", "bid": bid, "ask": ask, "spread": spread, "signal_strength": abs(change or 0), "model_expected_edge": model_edge, "model_expected_return": model_return, "model_expected_net_pnl": expected_net, "entry_reference": entry, "stop_distance": stop_distance if stop_distance else None, "stop_price": stop_price, "target_distance": target_distance, "target_price": target_price, "stop": stop_price, "target": target_price, "reward_to_risk": 1.5 if stop_distance else None, "quantity": quantity or None, "notional": entry * quantity if entry and quantity else None, "capital_required": entry * quantity if entry and quantity else None, "margin_required": entry * quantity if entry and quantity else None, "maximum_loss": risk, "economic_risk": risk, "estimated_holding_minutes": 60 if aligned else None, "estimated_capital_velocity": expected_net / max(entry * quantity, 1e-9) if expected_net and entry and quantity else None, "confidence": min(abs(change or 0) * 20, 1.0), "liquidity": min(1.0, float((bars or {}).get("bars", [{}])[-1].get("v", 0) or 0) / 1_000_000), "shortable": shortable, "tradable": bool((asset or {}).get("tradable")), "fractionable": (asset or {}).get("fractionable"), "volume": (bars or {}).get("bars", [{}])[-1].get("v") if (bars or {}).get("bars") else None})
    return rows


def _oanda_rows(symbol: str, health: object) -> list[dict[str, object]]:
    if not isinstance(health, dict) or health.get("status") != "OK":
        return _blocked(symbol, "forex", "oanda-practice", "NATIVE_OANDA_PRICING_UNAVAILABLE", health)
    base = require_oanda_practice_url(os.getenv("OANDA_PRACTICE_BASE_URL", "https://api-fxpractice.oanda.com"))
    account = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "")
    token = os.getenv("OANDA_PRACTICE_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    api_symbol = symbol.replace("/", "_")
    try:
        pricing = _get(f"{base}/v3/accounts/{account}/pricing?{urlencode({'instruments': api_symbol})}", headers)
        price = (pricing.get("prices") or [{}])[0]
        bid = float((price.get("bids") or [{}])[0].get("price"))
        ask = float((price.get("asks") or [{}])[0].get("price"))
        valid, spread, error = validate_native_quote(bid, ask)
        candles = _get(f"{base}/v3/instruments/{api_symbol}/candles?{urlencode({'granularity': 'M5', 'count': '30', 'price': 'M'})}", headers).get("candles", [])
        closes = [float(c["mid"]["c"]) for c in candles if c.get("complete") and c.get("mid", {}).get("c")]
        change = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 else None
        atr = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes[-15:]))) / max(len(closes[-15:]) - 1, 1) if len(closes) > 1 else None
        meta = _get(f"{base}/v3/accounts/{account}/instruments?{urlencode({'instruments': api_symbol})}", headers)
        instrument = (meta.get("instruments") or [{}])[0]
        margin_rate = float(instrument.get("marginRate", 0) or 0)
        rows = []
        for direction in ("LONG", "SHORT"):
            aligned = change is not None and ((change > 0 and direction == "LONG") or (change < 0 and direction == "SHORT"))
            stop_distance = max(atr or 0, spread * 3 if valid and spread is not None else 0)
            units = int(10 / stop_distance) if stop_distance > 0 else 0
            entry = ask if direction == "LONG" else bid
            stop = entry - stop_distance if direction == "LONG" else entry + stop_distance
            target = entry + stop_distance * 1.5 if direction == "LONG" else entry - stop_distance * 1.5
            gross = stop_distance * 1.5 * units
            cost = spread * units if valid and spread is not None else None
            net = gross - cost if cost is not None else None
            rows.append({"pillar": "forex", "provider": "oanda-practice", "provider_environment": "PRACTICE", "instrument": symbol, "api_instrument": api_symbol, "direction": direction, "strategy": "MOMENTUM", "status": "ELIGIBLE" if aligned and valid and net and net > 0 and units > 0 else error or "INSUFFICIENT_EDGE", "data_source": "OANDA_NATIVE_PRICING_CANDLES", "observed_at": datetime.now(UTC).isoformat(), "provider_timestamp": price.get("time"), "freshness": "FRESH", "bid": bid, "ask": ask, "spread": spread, "liquidity": max(0.0, 1.0 - (spread / max((bid + ask) / 2, 1e-9)) * 1000) if valid and spread is not None else None, "signal_strength": abs(change or 0), "model_expected_edge": net / max(units, 1) if net is not None else None, "model_expected_net_pnl": net, "model_expected_return_pct": net / max(abs(entry * units), 1) if net is not None else None, "entry_reference": entry, "stop_price": stop, "target_price": target, "stop_distance": stop_distance, "target_distance": stop_distance * 1.5, "reward_to_risk": 1.5 if stop_distance else None, "units": units, "notional": entry * units, "capital_required": min(1000.0, entry * units * margin_rate) if units else None, "margin_required": entry * units * margin_rate if units else None, "maximum_loss": stop_distance * units if units else None, "economic_risk": stop_distance * units if units else None, "margin_rate": margin_rate, "trade_units_precision": instrument.get("tradeUnitsPrecision"), "minimum_trade_size": instrument.get("minimumTradeSize"), "estimated_holding_minutes": 60, "estimated_capital_velocity": net / max(entry * units, 1) if net and units else None, "confidence": min(abs(change or 0) * 20, 1.0), "tradeable": price.get("status") == " tradeable" or price.get("tradeable", True)})
        return rows
    except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError) as exc:
        return _blocked(symbol, "forex", "oanda-practice", f"NATIVE_OANDA_{type(exc).__name__}", health)


def _blocked(symbol: str, pillar: str, provider: str, reason: str, provider_health: object) -> list[dict[str, object]]:
    return [{"pillar": pillar, "provider": provider, "provider_environment": "PAPER" if "alpaca" in provider else "PRACTICE", "instrument": symbol, "direction": direction, "strategy": "MOMENTUM", "status": "BLOCKED_PROVIDER", "block_reason": reason, "data_source": "NATIVE_PROVIDER", "freshness": "UNKNOWN", "provider_health": provider_health, "expected_edge": None, "expected_return": None, "capital_required": None, "margin_required": None, "maximum_loss": None, "estimated_holding_minutes": None, "capital_velocity_score": None} for direction in ("LONG", "SHORT")]
