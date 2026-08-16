from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class StreamEvent:
    provider: str
    kind: str
    symbol: str | None
    source_time: datetime | None
    received_at: datetime
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    latency_ms: float | None = None
    raw_type: str | None = None
    received_wall_ns: int = 0
    received_monotonic_ns: int = 0
    source_time_raw: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        for key in ("source_time", "received_at"):
            value = payload[key]
            payload[key] = None if value is None else value.isoformat()
        return json.dumps(payload, sort_keys=True)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        if "." in normalized:
            prefix, suffix = normalized.split(".", 1)
            zone = "+00:00" if suffix.endswith("+00:00") else ""
            digits = suffix.removesuffix("+00:00")[:6]
            try:
                parsed = datetime.fromisoformat(f"{prefix}.{digits}{zone}")
            except ValueError:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latency_ms(source_time: datetime | None, received_at: datetime) -> float | None:
    if source_time is None:
        return None
    return max((received_at - source_time).total_seconds() * 1000.0, 0.0)


def _receive_stamps() -> tuple[datetime, int, int]:
    wall_ns = time.time_ns()
    monotonic_ns = time.perf_counter_ns()
    received = datetime.fromtimestamp(wall_ns / 1_000_000_000, tz=UTC)
    return received, wall_ns, monotonic_ns


def normalize_alpaca_message(message: dict[str, object]) -> StreamEvent | None:
    if message.get("T") != "q":
        return None
    received, wall_ns, monotonic_ns = _receive_stamps()
    source_raw = str(message.get("t")) if message.get("t") is not None else None
    source = parse_timestamp(source_raw)
    return StreamEvent(
        provider="alpaca",
        kind="quote",
        symbol=str(message.get("S")) if message.get("S") is not None else None,
        source_time=source,
        received_at=received,
        bid=float(message["bp"]) if message.get("bp") is not None else None,
        ask=float(message["ap"]) if message.get("ap") is not None else None,
        bid_size=float(message["bs"]) if message.get("bs") is not None else None,
        ask_size=float(message["as"]) if message.get("as") is not None else None,
        latency_ms=_latency_ms(source, received),
        raw_type="q",
        received_wall_ns=wall_ns,
        received_monotonic_ns=monotonic_ns,
        source_time_raw=source_raw,
    )


def _best_price(levels: object) -> tuple[float | None, float | None]:
    if not isinstance(levels, list) or not levels:
        return None, None
    level = levels[0]
    if not isinstance(level, dict):
        return None, None
    price = float(level["price"]) if level.get("price") is not None else None
    liquidity = float(level["liquidity"]) if level.get("liquidity") is not None else None
    return price, liquidity


def normalize_oanda_message(message: dict[str, object]) -> StreamEvent | None:
    message_type = str(message.get("type") or "")
    if message_type not in {"PRICE", "HEARTBEAT"}:
        return None
    received, wall_ns, monotonic_ns = _receive_stamps()
    source_raw = str(message.get("time")) if message.get("time") is not None else None
    source = parse_timestamp(source_raw)
    if message_type == "HEARTBEAT":
        return StreamEvent(
            provider="oanda",
            kind="heartbeat",
            symbol=None,
            source_time=source,
            received_at=received,
            latency_ms=_latency_ms(source, received),
            raw_type=message_type,
            received_wall_ns=wall_ns,
            received_monotonic_ns=monotonic_ns,
            source_time_raw=source_raw,
        )
    bid, bid_size = _best_price(message.get("bids"))
    ask, ask_size = _best_price(message.get("asks"))
    instrument = message.get("instrument")
    symbol = str(instrument).replace("_", "/") if instrument is not None else None
    return StreamEvent(
        provider="oanda",
        kind="quote",
        symbol=symbol,
        source_time=source,
        received_at=received,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        latency_ms=_latency_ms(source, received),
        raw_type=message_type,
        received_wall_ns=wall_ns,
        received_monotonic_ns=monotonic_ns,
        source_time_raw=source_raw,
    )


def validate_oanda_price_events(events: list[StreamEvent]) -> None:
    """Require at least one executable-looking PRICE event before readiness.

    OANDA heartbeats prove that authentication and transport are alive, but they
    do not prove that the requested instrument is currently producing prices.
    """

    quotes = [
        event
        for event in events
        if event.provider == "oanda"
        and event.kind == "quote"
        and event.symbol
        and event.bid is not None
        and event.ask is not None
        and event.bid > 0
        and event.ask > 0
        and event.ask >= event.bid
    ]
    if quotes:
        return
    heartbeat_count = sum(
        1 for event in events if event.provider == "oanda" and event.kind == "heartbeat"
    )
    raise RuntimeError(
        "OANDA stream transport is alive but no valid PRICE event was received "
        f"({heartbeat_count} heartbeat events). Do not submit a practice order yet."
    )


def _select_oanda_account_id(
    accounts_payload: dict[str, object],
    configured_account_id: str = "",
) -> str:
    accounts = accounts_payload.get("accounts")
    if not isinstance(accounts, list):
        accounts = []
    account_ids = [
        str(account.get("id"))
        for account in accounts
        if isinstance(account, dict) and account.get("id")
    ]

    configured = configured_account_id.strip()
    if configured:
        if account_ids and configured not in account_ids:
            raise RuntimeError("Configured OANDA practice account is not authorized by this token")
        return configured

    if len(account_ids) == 1:
        return account_ids[0]
    if not account_ids:
        raise RuntimeError("OANDA token returned no accessible practice accounts")
    raise RuntimeError(
        "OANDA token can access multiple accounts. Set OANDA_PRACTICE_ACCOUNT_ID "
        "to choose one explicitly."
    )


def _discover_oanda_account_id(token: str, timeout_seconds: float) -> str:
    configured = os.getenv("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
    rest_base = os.getenv(
        "OANDA_PRACTICE_BASE_URL",
        "https://api-fxpractice.oanda.com",
    ).rstrip("/")
    request = Request(
        f"{rest_base}/v3/accounts",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _select_oanda_account_id(payload, configured)


async def stream_alpaca_quotes(
    symbols: list[str],
    *,
    max_events: int = 20,
    feed: str = "iex",
    timeout_seconds: float = 30.0,
) -> list[StreamEvent]:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets is required. Install with: python -m pip install -e '.[streaming]'"
        ) from exc

    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Missing ALPACA_PAPER_API_KEY or ALPACA_PAPER_SECRET_KEY")

    normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if not normalized_symbols:
        raise ValueError("At least one Alpaca symbol is required")

    url = os.getenv(
        "ALPACA_MARKETDATA_STREAM_URL",
        f"wss://stream.data.alpaca.markets/v2/{feed}",
    )
    events: list[StreamEvent] = []

    async with websockets.connect(url, open_timeout=timeout_seconds) as socket:
        connected = json.loads(await asyncio.wait_for(socket.recv(), timeout_seconds))
        if not any(item.get("msg") == "connected" for item in connected):
            raise RuntimeError(f"Unexpected Alpaca connect response: {connected}")

        await socket.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
        auth = json.loads(await asyncio.wait_for(socket.recv(), timeout_seconds))
        if not any(item.get("msg") == "authenticated" for item in auth):
            raise RuntimeError(f"Alpaca stream authentication failed: {auth}")

        await socket.send(json.dumps({"action": "subscribe", "quotes": normalized_symbols}))
        while len(events) < max_events:
            frame = await asyncio.wait_for(socket.recv(), timeout_seconds)
            messages = json.loads(frame)
            for message in messages:
                if message.get("T") == "error":
                    raise RuntimeError(f"Alpaca stream error: {message}")
                event = normalize_alpaca_message(message)
                if event is not None:
                    events.append(event)
                    print(event.to_json(), flush=True)
                    if len(events) >= max_events:
                        break
    return events


def stream_oanda_prices(
    symbols: list[str],
    *,
    max_events: int = 20,
    timeout_seconds: float = 30.0,
) -> list[StreamEvent]:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing OANDA_PRACTICE_TOKEN")
    account_id = _discover_oanda_account_id(token, timeout_seconds)

    instruments = [
        symbol.strip().upper().replace("/", "_")
        for symbol in symbols
        if symbol.strip()
    ]
    if not instruments:
        raise ValueError("At least one OANDA symbol is required")

    base = os.getenv(
        "OANDA_PRACTICE_STREAM_URL",
        "https://stream-fxpractice.oanda.com",
    ).rstrip("/")
    query = urlencode({"instruments": ",".join(instruments), "snapshot": "true"})
    url = f"{base}/v3/accounts/{account_id}/pricing/stream?{query}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept-Datetime-Format": "RFC3339",
            "Accept": "application/json",
        },
        method="GET",
    )
    events: list[StreamEvent] = []
    with urlopen(request, timeout=timeout_seconds) as response:
        while len(events) < max_events:
            line = response.readline()
            if not line:
                break
            message = json.loads(line.decode("utf-8"))
            event = normalize_oanda_message(message)
            if event is not None:
                events.append(event)
                print(event.to_json(), flush=True)
    validate_oanda_price_events(events)
    return events
