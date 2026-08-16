from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .brokers.practice_orders import _oanda_account_id
from .streaming import parse_timestamp


@dataclass(frozen=True)
class BrokerEvent:
    broker: str
    event_type: str
    received_at: datetime
    source_time: datetime | None
    order_id: str | None = None
    client_order_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    quantity: float | None = None
    price: float | None = None
    status: str | None = None
    raw: dict[str, object] | None = None


def normalize_alpaca_trade_update(message: dict[str, object]) -> BrokerEvent | None:
    if message.get("stream") != "trade_updates":
        return None
    data = message.get("data")
    if not isinstance(data, dict):
        return None
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    return BrokerEvent(
        broker="alpaca-paper",
        event_type=str(data.get("event") or "unknown"),
        received_at=datetime.now(UTC),
        source_time=parse_timestamp(data.get("timestamp")),
        order_id=None if order.get("id") is None else str(order.get("id")),
        client_order_id=(
            None if order.get("client_order_id") is None else str(order.get("client_order_id"))
        ),
        symbol=None if order.get("symbol") is None else str(order.get("symbol")),
        side=None if order.get("side") is None else str(order.get("side")),
        quantity=None if data.get("qty") is None else float(data.get("qty")),
        price=None if data.get("price") is None else float(data.get("price")),
        status=None if order.get("status") is None else str(order.get("status")),
        raw=data,
    )


def normalize_oanda_transaction(message: dict[str, object]) -> BrokerEvent | None:
    event_type = str(message.get("type") or "")
    if not event_type:
        return None
    symbol = message.get("instrument")
    units = message.get("units")
    side = None
    quantity = None
    if units is not None:
        signed = float(units)
        side = "buy" if signed > 0 else "sell" if signed < 0 else None
        quantity = abs(signed)
    return BrokerEvent(
        broker="oanda-practice",
        event_type=event_type.lower(),
        received_at=datetime.now(UTC),
        source_time=parse_timestamp(message.get("time")),
        order_id=None if message.get("orderID") is None else str(message.get("orderID")),
        client_order_id=None,
        symbol=None if symbol is None else str(symbol).replace("_", "/"),
        side=side,
        quantity=quantity,
        price=None if message.get("price") is None else float(message.get("price")),
        status=event_type,
        raw=message,
    )


async def stream_alpaca_trade_updates(
    *,
    max_events: int = 20,
    timeout_seconds: float = 30.0,
) -> list[BrokerEvent]:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets is required. Install with: python -m pip install -e '.[streaming]'"
        ) from exc

    key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Missing Alpaca paper credentials")
    url = os.getenv("ALPACA_TRADING_STREAM_URL", "wss://paper-api.alpaca.markets/stream")
    events: list[BrokerEvent] = []

    async with websockets.connect(url, open_timeout=timeout_seconds) as socket:
        await socket.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
        auth_frame = await asyncio.wait_for(socket.recv(), timeout_seconds)
        auth_payload = _decode_json_frame(auth_frame)
        if not isinstance(auth_payload, dict):
            raise RuntimeError("Unexpected Alpaca trading-stream auth response")
        auth_data = auth_payload.get("data") if isinstance(auth_payload.get("data"), dict) else {}
        if auth_payload.get("stream") != "authorization" or auth_data.get("status") != "authorized":
            raise RuntimeError(f"Alpaca trading stream authentication failed: {auth_payload}")
        await socket.send(json.dumps({"action": "listen", "data": {"streams": ["trade_updates"]}}))
        while len(events) < max_events:
            frame = await asyncio.wait_for(socket.recv(), timeout_seconds)
            payload = _decode_json_frame(frame)
            if not isinstance(payload, dict):
                continue
            event = normalize_alpaca_trade_update(payload)
            if event is not None:
                events.append(event)
    return events


def _decode_json_frame(frame: str | bytes) -> object:
    if isinstance(frame, bytes):
        frame = frame.decode("utf-8")
    return json.loads(frame)


def stream_oanda_transactions(
    *,
    max_events: int = 20,
    timeout_seconds: float = 30.0,
) -> list[BrokerEvent]:
    token = os.getenv("OANDA_PRACTICE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing OANDA practice token")
    account_id = _oanda_account_id()
    base = os.getenv("OANDA_PRACTICE_STREAM_URL", "https://stream-fxpractice.oanda.com").rstrip("/")
    request = Request(
        f"{base}/v3/accounts/{account_id}/transactions/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept-Datetime-Format": "RFC3339",
            "Accept": "application/json",
        },
        method="GET",
    )
    events: list[BrokerEvent] = []
    with urlopen(request, timeout=timeout_seconds) as response:
        while len(events) < max_events:
            line = response.readline()
            if not line:
                break
            payload = json.loads(line.decode("utf-8"))
            event = normalize_oanda_transaction(payload)
            if event is not None:
                events.append(event)
    return events
