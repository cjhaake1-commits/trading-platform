"""Safe loader for the environment used by standalone runtime tools."""
from __future__ import annotations

import os
from pathlib import Path


def _read_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            loaded[key] = value
    return loaded


def load_runtime_environment(*, repo_env: str | Path = ".env", kalshi_env: str | Path = "/home/cjhaake/.config/trading-platform/kalshi-demo-execution.env", authoritative: bool = False) -> dict[str, object]:
    repo = Path(repo_env)
    kalshi = Path(kalshi_env)
    values = {**_read_file(repo), **_read_file(kalshi)}
    allowlist = {"ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY", "ALPACA_PAPER_BASE_URL", "ALPACA_DATA_BASE_URL", "OANDA_PRACTICE_TOKEN", "OANDA_PRACTICE_ACCOUNT_ID", "OANDA_PRACTICE_BASE_URL", "KALSHI_ENV", "KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_PAPER_CAPITAL", "KALSHI_RESEARCH_ENABLED", "KALSHI_ENABLED", "KALSHI_TRADING_ENABLED", "KALSHI_LIVE_TRADING_ENABLED"}
    loaded: dict[str, str] = {}
    for key, value in values.items():
        if authoritative and key in allowlist:
            os.environ[key] = value
            loaded[key] = "PRESENT" if value else "EMPTY"
        elif not authoritative and key not in os.environ:
            os.environ[key] = value
            loaded[key] = "PRESENT" if value else "EMPTY"
    names = ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY", "OANDA_PRACTICE_TOKEN", "KALSHI_ENV", "KALSHI_API_KEY_ID")
    return {"repo_env": "PRESENT" if repo.exists() else "MISSING", "kalshi_env": "PRESENT" if kalshi.exists() else "MISSING", "mode": "AUTHORITATIVE" if authoritative else "SAFE_DEFAULT", "loaded": loaded, "presence": {name: "PRESENT" if os.getenv(name) else "MISSING" for name in names}}
