from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from .streaming import parse_timestamp


@dataclass(frozen=True)
class NewsEvent:
    provider: str
    article_id: str
    headline: str
    summary: str
    symbols: tuple[str, ...]
    source_time: datetime | None
    received_at: datetime
    author: str | None = None
    source: str | None = None


def normalize_alpaca_news(message: dict[str, object]) -> NewsEvent | None:
    if message.get("T") != "n":
        return None
    received = datetime.now(UTC)
    symbols = message.get("symbols")
    if not isinstance(symbols, list):
        symbols = []
    return NewsEvent(
        provider="alpaca_news",
        article_id=str(message.get("id") or ""),
        headline=str(message.get("headline") or ""),
        summary=str(message.get("summary") or ""),
        symbols=tuple(str(symbol).upper() for symbol in symbols),
        source_time=parse_timestamp(message.get("created_at")),
        received_at=received,
        author=None if message.get("author") is None else str(message.get("author")),
        source=None if message.get("source") is None else str(message.get("source")),
    )


async def stream_alpaca_news(
    symbols: list[str] | None = None,
    *,
    max_events: int = 20,
    timeout_seconds: float = 30.0,
) -> list[NewsEvent]:
    """Stream Alpaca real-time news without placing it on the execution thread."""
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

    requested = [symbol.strip().upper() for symbol in (symbols or ["*"]) if symbol.strip()]
    if not requested:
        requested = ["*"]
    url = os.getenv(
        "ALPACA_NEWS_STREAM_URL",
        "wss://stream.data.alpaca.markets/v1beta1/news",
    )
    events: list[NewsEvent] = []
    async with websockets.connect(url, open_timeout=timeout_seconds) as socket:
        connected = json.loads(await asyncio.wait_for(socket.recv(), timeout_seconds))
        if not any(item.get("msg") == "connected" for item in connected):
            raise RuntimeError(f"Unexpected Alpaca news connect response: {connected}")
        await socket.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
        auth = json.loads(await asyncio.wait_for(socket.recv(), timeout_seconds))
        if not any(item.get("msg") == "authenticated" for item in auth):
            raise RuntimeError(f"Alpaca news authentication failed: {auth}")
        await socket.send(json.dumps({"action": "subscribe", "news": requested}))
        while len(events) < max_events:
            frame = await asyncio.wait_for(socket.recv(), timeout_seconds)
            messages = json.loads(frame)
            for message in messages:
                if message.get("T") == "error":
                    raise RuntimeError(f"Alpaca news stream error: {message}")
                event = normalize_alpaca_news(message)
                if event is not None:
                    events.append(event)
                    if len(events) >= max_events:
                        break
    return events
