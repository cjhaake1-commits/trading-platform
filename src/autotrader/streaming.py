from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic
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
    ask_size