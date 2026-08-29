from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = "trading-platform-research/0.1 contact=research@example.invalid"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class PublicObservation:
    source: str
    event_type: str
    observed_at: str
    source_time: str | None = None
    symbol: str | None = None
    entity: str | None = None
    title: str | None = None
    value: float | None = None
    unit: str | None = None
    url: str | None = None
    metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata or {})
        return payload


class PublicIntelligenceStore:
    """Append-only research store for lawful public observations.

    This database is intentionally separate from broker/execution state. Rows
    are research evidence only and have no direct order-placement authority.
    """

    def __init__(self, path: str | Path = "var/autotrader/public-intelligence.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source_time TEXT,
                    symbol TEXT,
                    entity TEXT,
                    title TEXT,
                    value REAL,
                    unit TEXT,
                    url TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_public_observation_source_time
                    ON observations(source, source_time);
                CREATE INDEX IF NOT EXISTS idx_public_observation_symbol_time
                    ON observations(symbol, source_time);
                CREATE TABLE IF NOT EXISTS source_health (
                    source TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    last_attempt TEXT NOT NULL,
                    last_success TEXT,
                    records INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL,
                    error TEXT
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, rows: Iterable[PublicObservation]) -> int:
        payload = list(rows)
        if not payload:
            return 0
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO observations(
                    source,event_type,observed_at,source_time,symbol,entity,title,
                    value,unit,url,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        row.source,
                        row.event_type,
                        row.observed_at,
                        row.source_time,
                        row.symbol,
                        row.entity,
                        row.title,
                        row.value,
                        row.unit,
                        row.url,
                        json.dumps(dict(row.metadata or {}), sort_keys=True, default=str),
                    )
                    for row in payload
                ],
            )
        return len(payload)

    def health(self, source: str, *, state: str, records: int, latency_ms: float, error: str | None = None) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_health(source,state,last_attempt,last_success,records,latency_ms,error)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(source) DO UPDATE SET
                    state=excluded.state,
                    last_attempt=excluded.last_attempt,
                    last_success=CASE WHEN excluded.state='CONNECTED' THEN excluded.last_success ELSE source_health.last_success END,
                    records=excluded.records,
                    latency_ms=excluded.latency_ms,
                    error=excluded.error
                """,
                (source, state, now, now if state == "CONNECTED" else None, records, latency_ms, error),
            )

    def source_health(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM source_health ORDER BY source")]


class JsonHttpClient:
    def __init__(self, *, timeout_seconds: float = 12.0, user_agent: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or os.getenv("PUBLIC_DATA_USER_AGENT", DEFAULT_USER_AGENT)

    def json(self, url: str, *, headers: Mapping[str, str] | None = None) -> Any:
        merged = {"User-Agent": self.user_agent, "Accept": "application/json"}
        merged.update(dict(headers or {}))
        request = Request(url, headers=merged, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def text(self, url: str, *, headers: Mapping[str, str] | None = None) -> str:
        merged = {"User-Agent": self.user_agent, "Accept": "*/*"}
        merged.update(dict(headers or {}))
        request = Request(url, headers=merged, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")


class TreasuryYieldCurveSource:
    name = "treasury_yield_curve"

    def __init__(self, client: JsonHttpClient | None = None) -> None:
        self.client = client or JsonHttpClient()

    def collect(self, now: datetime) -> list[PublicObservation]:
        year = now.astimezone(UTC).year
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
            f"?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
        )
        root = ET.fromstring(self.client.text(url))
        rows: list[PublicObservation] = []
        for entry in root.iter():
            if not entry.tag.endswith("entry"):
                continue
            content = next((child for child in entry if child.tag.endswith("content")), None)
            if content is None:
                continue
            properties = next(iter(content), None)
            if properties is None:
                continue
            fields: dict[str, str] = {}
            for child in properties:
                key = child.tag.rsplit("}", 1)[-1]
                if child.text:
                    fields[key] = child.text
            source_time = fields.get("NEW_DATE") or fields.get("Date")
            for key, value in fields.items():
                if not key.startswith("BC_"):
                    continue
                try:
                    number = float(value)
                except ValueError:
                    continue
                rows.append(
                    PublicObservation(
                        source=self.name,
                        event_type="yield_curve",
                        observed_at=now.astimezone(UTC).isoformat(),
                        source_time=source_time,
                        title=key,
                        value=number,
                        unit="percent",
                        url=url,
                        metadata={"series": key},
                    )
                )
        return rows[-64:]


class SecSubmissionsSource:
    name = "sec_edgar"

    def __init__(self, client: JsonHttpClient | None = None, ciks: Iterable[str] | None = None) -> None:
        self.client = client or JsonHttpClient()
        configured = ciks if ciks is not None else _split_csv(os.getenv("PUBLIC_SEC_CIKS", ""))
        self.ciks = tuple(str(cik).strip().zfill(10) for cik in configured if str(cik).strip())

    def collect(self, now: datetime) -> list[PublicObservation]:
        observations: list[PublicObservation] = []
        for cik in self.ciks:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            payload = self.client.json(url)
            recent = ((payload.get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
            forms = recent.get("form") or []
            accession = recent.get("accessionNumber") or []
            filed = recent.get("filingDate") or []
            primary = recent.get("primaryDocument") or []
            count = min(len(forms), len(accession), len(filed), len(primary), 25)
            for index in range(count):
                acc = str(accession[index]).replace("-", "")
                document = str(primary[index])
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{document}"
                observations.append(
                    PublicObservation(
                        source=self.name,
                        event_type="filing",
                        observed_at=now.astimezone(UTC).isoformat(),
                        source_time=str(filed[index]),
                        entity=str(payload.get("name") or cik),
                        title=str(forms[index]),
                        url=filing_url,
                        metadata={"cik": cik, "form": forms[index], "accession": accession[index]},
                    )
                )
        return observations


class GdeltSource:
    name = "gdelt"

    def __init__(self, client: JsonHttpClient | None = None, query: str | None = None) -> None:
        self.client = client or JsonHttpClient()
        self.query = query or os.getenv(
            "PUBLIC_GDELT_QUERY",
            '(economy OR inflation OR "interest rates" OR oil OR bitcoin OR stocks OR sanctions OR war)',
        )

    def collect(self, now: datetime) -> list[PublicObservation]:
        params = urlencode(
            {
                "query": self.query,
                "mode": "ArtList",
                "maxrecords": os.getenv("PUBLIC_GDELT_MAX_RECORDS", "75"),
                "format": "json",
                "sort": "HybridRel",
            }
        )
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
        payload = self.client.json(url)
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        observations: list[PublicObservation] = []
        for article in articles if isinstance(articles, list) else []:
            if not isinstance(article, dict):
                continue
            observations.append(
                PublicObservation(
                    source=self.name,
                    event_type="global_news",
                    observed_at=now.astimezone(UTC).isoformat(),
                    source_time=str(article.get("seendate") or "") or None,
                    entity=str(article.get("domain") or "") or None,
                    title=str(article.get("title") or "") or None,
                    url=str(article.get("url") or "") or None,
                    metadata={
                        "language": article.get("language"),
                        "sourcecountry": article.get("sourcecountry"),
                        "socialimage": article.get("socialimage"),
                    },
                )
            )
        return observations


class FredSource:
    name = "fred"

    def __init__(self, client: JsonHttpClient | None = None) -> None:
        self.client = client or JsonHttpClient()
        self.api_key = os.getenv("FRED_API_KEY", "").strip()
        self.series = _split_csv(os.getenv("PUBLIC_FRED_SERIES", "DFF,CPIAUCSL,UNRATE,DGS10,DGS2,VIXCLS"))

    def collect(self, now: datetime) -> list[PublicObservation]:
        if not self.api_key:
            return []
        rows: list[PublicObservation] = []
        for series_id in self.series:
            params = urlencode(
                {
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": "5",
                }
            )
            url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
            payload = self.client.json(url)
            for item in payload.get("observations", []) if isinstance(payload, dict) else []:
                try:
                    value = float(item.get("value"))
                except (TypeError, ValueError):
                    continue
                rows.append(
                    PublicObservation(
                        source=self.name,
                        event_type="macro_series",
                        observed_at=now.astimezone(UTC).isoformat(),
                        source_time=str(item.get("date") or "") or None,
                        title=series_id,
                        value=value,
                        url=url,
                        metadata={"series_id": series_id, "realtime_start": item.get("realtime_start")},
                    )
                )
        return rows


class EiaSource:
    name = "eia"

    def __init__(self, client: JsonHttpClient | None = None) -> None:
        self.client = client or JsonHttpClient()
        self.api_key = os.getenv("EIA_API_KEY", "").strip()
        self.route = os.getenv("PUBLIC_EIA_ROUTE", "/v2/petroleum/pri/spt/data/").strip()

    def collect(self, now: datetime) -> list[PublicObservation]:
        if not self.api_key:
            return []
        params = urlencode({"api_key": self.api_key, "length": "25", "sort[0][column]": "period", "sort[0][direction]": "desc"})
        url = f"https://api.eia.gov{self.route}?{params}"
        payload = self.client.json(url)
        response = payload.get("response", {}) if isinstance(payload, dict) else {}
        data = response.get("data", []) if isinstance(response, dict) else []
        rows: list[PublicObservation] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = None
            rows.append(
                PublicObservation(
                    source=self.name,
                    event_type="energy",
                    observed_at=now.astimezone(UTC).isoformat(),
                    source_time=str(item.get("period") or "") or None,
                    entity=str(item.get("product-name") or item.get("series-description") or "") or None,
                    title=str(item.get("series") or item.get("product") or "") or None,
                    value=numeric,
                    unit=str(item.get("units") or "") or None,
                    url=url,
                    metadata=item,
                )
            )
        return rows


class ConfiguredJsonSource:
    """Generic lawful-public JSON endpoint adapter for CFTC/FINRA/etc.

    Endpoint URLs are deliberately supplied by configuration because public
    dataset identifiers and licensing/registration requirements can change.
    """

    def __init__(self, name: str, env_url: str, client: JsonHttpClient | None = None) -> None:
        self.name = name
        self.env_url = env_url
        self.client = client or JsonHttpClient()

    def collect(self, now: datetime) -> list[PublicObservation]:
        url = os.getenv(self.env_url, "").strip()
        if not url:
            return []
        payload = self.client.json(url)
        data = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        rows: list[PublicObservation] = []
        for item in data[:250] if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            rows.append(
                PublicObservation(
                    source=self.name,
                    event_type="public_dataset",
                    observed_at=now.astimezone(UTC).isoformat(),
                    source_time=str(item.get("date") or item.get("report_date_as_yyyy_mm_dd") or item.get("period") or "") or None,
                    symbol=str(item.get("symbol") or item.get("contract_market_name") or "") or None,
                    title=str(item.get("title") or item.get("market_and_exchange_names") or "") or None,
                    url=url,
                    metadata=item,
                )
            )
        return rows


class PublicIntelligenceCollector:
    """Collect independent public research sources without broker control."""

    def __init__(self, store: PublicIntelligenceStore | None = None, sources: Iterable[Any] | None = None) -> None:
        self.store = store or PublicIntelligenceStore()
        if sources is None:
            sources = (
                TreasuryYieldCurveSource(),
                SecSubmissionsSource(),
                GdeltSource(),
                FredSource(),
                EiaSource(),
                ConfiguredJsonSource("cftc", "CFTC_PUBLIC_API_URL"),
                ConfiguredJsonSource("finra", "FINRA_PUBLIC_API_URL"),
            )
        self.sources = tuple(sources)

    def collect_once(self, now: datetime | None = None) -> dict[str, object]:
        observed = now or datetime.now(UTC)
        results: dict[str, dict[str, object]] = {}
        for source in self.sources:
            started = time.perf_counter()
            try:
                rows = source.collect(observed)
                count = self.store.append(rows)
                latency = (time.perf_counter() - started) * 1000.0
                state = "CONNECTED" if count else "IDLE"
                self.store.health(source.name, state=state, records=count, latency_ms=latency)
                results[source.name] = {"state": state, "records": count, "latency_ms": latency}
            except Exception as exc:
                latency = (time.perf_counter() - started) * 1000.0
                error = f"{type(exc).__name__}: {exc}"
                self.store.health(source.name, state="DEGRADED", records=0, latency_ms=latency, error=error)
                results[source.name] = {"state": "DEGRADED", "records": 0, "latency_ms": latency, "error": error}
        return {
            "observed_at": observed.astimezone(UTC).isoformat(),
            "sources": results,
            "records": sum(int(item.get("records") or 0) for item in results.values()),
            "research_only": True,
            "broker_control": False,
        }


async def stream_coinbase_and_bluesky(
    *,
    store_path: str = "var/autotrader/public-intelligence.db",
    products: Iterable[str] | None = None,
    bluesky_collections: Iterable[str] | None = None,
    max_events: int | None = None,
) -> dict[str, int]:
    """Consume public high-rate streams for research-only pattern learning.

    Coinbase provides market microstructure observations. Bluesky Jetstream
    provides public social activity. Both are normalized into the same durable
    event store. This function has no broker imports and cannot submit orders.
    """

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("Install the optional streaming dependency: pip install -e '.[streaming]'") from exc

    store = PublicIntelligenceStore(store_path)
    product_ids = tuple(products or _split_csv(os.getenv("PUBLIC_COINBASE_PRODUCTS", "BTC-USD,ETH-USD,SOL-USD")))
    collections = tuple(bluesky_collections or _split_csv(os.getenv("PUBLIC_BLUESKY_COLLECTIONS", "app.bsky.feed.post")))
    counts = {"coinbase": 0, "bluesky": 0}
    stop = asyncio.Event()

    async def coinbase() -> None:
        url = os.getenv("PUBLIC_COINBASE_WS", "wss://ws-feed.exchange.coinbase.com")
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "product_ids": list(product_ids),
                        "channels": ["ticker", "level2"],
                    }
                )
            )
            async for raw in socket:
                message = json.loads(raw)
                kind = str(message.get("type") or "")
                if kind not in {"ticker", "snapshot", "l2update"}:
                    continue
                metadata: dict[str, object] = {"type": kind}
                for key in ("price", "best_bid", "best_ask", "last_size", "side", "changes", "bids", "asks"):
                    if key in message:
                        metadata[key] = message[key]
                store.append(
                    [
                        PublicObservation(
                            source="coinbase",
                            event_type="market_microstructure",
                            observed_at=_utc_now(),
                            source_time=str(message.get("time") or "") or None,
                            symbol=str(message.get("product_id") or "") or None,
                            value=float(message["price"]) if message.get("price") is not None else None,
                            metadata=metadata,
                        )
                    ]
                )
                counts["coinbase"] += 1
                if max_events is not None and sum(counts.values()) >= max_events:
                    stop.set()
                    return

    async def bluesky() -> None:
        base = os.getenv("PUBLIC_BLUESKY_JETSTREAM", "wss://jetstream2.us-east.bsky.network/subscribe")
        params = [("wantedCollections", collection) for collection in collections]
        params.append(("compress", "false"))
        url = f"{base}?{urlencode(params)}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
            async for raw in socket:
                message = json.loads(raw)
                commit = message.get("commit") if isinstance(message, dict) else None
                record = commit.get("record") if isinstance(commit, dict) else None
                if not isinstance(record, dict):
                    continue
                text = str(record.get("text") or "")
                if not text:
                    continue
                store.append(
                    [
                        PublicObservation(
                            source="bluesky",
                            event_type="social_post",
                            observed_at=_utc_now(),
                            source_time=str(message.get("time_us") or "") or None,
                            entity=str(message.get("did") or "") or None,
                            title=text[:280],
                            metadata={
                                "collection": commit.get("collection"),
                                "operation": commit.get("operation"),
                                "cid": commit.get("cid"),
                            },
                        )
                    ]
                )
                counts["bluesky"] += 1
                if max_events is not None and sum(counts.values()) >= max_events:
                    stop.set()
                    return

    tasks = [asyncio.create_task(coinbase()), asyncio.create_task(bluesky())]
    if max_events is None:
        await asyncio.gather(*tasks)
    else:
        await stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return counts
