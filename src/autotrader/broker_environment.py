from __future__ import annotations

from urllib.parse import urlparse

ALPACA_PAPER_HOST = "paper-api.alpaca.markets"
OANDA_PRACTICE_HOST = "api-fxpractice.oanda.com"


def require_alpaca_paper_url(url: str) -> str:
    return _require_https_host(url, ALPACA_PAPER_HOST, "Alpaca PAPER")


def require_oanda_practice_url(url: str) -> str:
    return _require_https_host(url, OANDA_PRACTICE_HOST, "OANDA practice")


def _require_https_host(url: str, expected_host: str, label: str) -> str:
    normalized = url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        raise RuntimeError(f"Safety lock: {label} requires https://{expected_host}")
    return normalized
