from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree


@dataclass(frozen=True)
class RelayPayload:
    provider: str
    received_at: datetime
    payload: object
    source_url: str


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> RelayPayload:
    request = Request(url, headers=headers or {}, method="GET")
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return RelayPayload("http-json", datetime.now(UTC), payload, url)


def fetch_sec_submissions(cik: str, *, timeout: float = 15.0) -> RelayPayload:
    """Fetch current SEC submissions for one CIK from data.sec.gov.

    SEC requires automated clients to identify themselves. Configure
    SEC_USER_AGENT with an application/organization name and contact address.
    """

    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is required for automated SEC access")
    digits = "".join(character for character in cik if character.isdigit())
    if not digits:
        raise ValueError("CIK must contain digits")
    normalized = digits.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{normalized}.json"
    result = _fetch_json(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        timeout=timeout,
    )
    return RelayPayload("sec_edgar", result.received_at, result.payload, result.source_url)


def fetch_bls_latest(series_id: str, *, timeout: float = 15.0) -> RelayPayload:
    """Fetch the latest published observation for one BLS series."""

    normalized = series_id.strip().upper()
    if not normalized:
        raise ValueError("BLS series_id is required")
    url = (
        "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        f"{quote(normalized, safe='_-#')}?latest=true"
    )
    result = _fetch_json(url, headers={"Accept": "application/json"}, timeout=timeout)
    return RelayPayload("bls", result.received_at, result.payload, result.source_url)


def fetch_rss(
    provider: str,
    url: str,
    *,
    user_agent: str = "autonomous-trading-platform/0.1",
    timeout: float = 15.0,
) -> RelayPayload:
    """Fetch and normalize a public RSS/Atom relay into a small entry list."""

    request = Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/rss+xml, application/atom+xml, text/xml"},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    root = ElementTree.fromstring(raw)
    entries: list[dict[str, str | None]] = []

    rss_items = root.findall(".//item")
    if rss_items:
        for item in rss_items:
            entries.append(
                {
                    "title": _child_text(item, "title"),
                    "link": _child_text(item, "link"),
                    "published": _child_text(item, "pubDate"),
                    "summary": _child_text(item, "description"),
                }
            )
    else:
        namespace = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f".//{namespace}entry"):
            link = entry.find(f"{namespace}link")
            entries.append(
                {
                    "title": _child_text(entry, f"{namespace}title"),
                    "link": None if link is None else link.attrib.get("href"),
                    "published": (
                        _child_text(entry, f"{namespace}published")
                        or _child_text(entry, f"{namespace}updated")
                    ),
                    "summary": (
                        _child_text(entry, f"{namespace}summary")
                        or _child_text(entry, f"{namespace}content")
                    ),
                }
            )

    return RelayPayload(provider, datetime.now(UTC), entries, url)


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    child = element.find(name)
    if child is None or child.text is None:
        return None
    return child.text.strip()
