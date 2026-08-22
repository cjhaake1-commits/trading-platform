#!/usr/bin/env python3
"""One-time Saxo SIM PKCE bootstrap; never prints credential values."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from autotrader.brokers.saxo_sim import (
    SaxoConfigurationError,
    SaxoSimAdapter,
    SaxoTokenStore,
    pkce_pair,
    saxo_authorization_url,
)


def _load_dotenv() -> None:
    path = Path(".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def _state_path() -> Path:
    return Path(os.getenv("SAXO_PKCE_STATE_STORE", "~/.local/share/trading-platform/saxo-pkce-state.json")).expanduser()


def _save_state(value: dict[str, str]) -> None:
    path = _state_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _load_state() -> dict[str, str]:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError):
        return {}


def authorize() -> None:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    _save_state({"state": state, "code_verifier": verifier, "created_at": str(time.time())})
    print("SAXO PKCE AUTHORIZATION REQUIRED")
    print(saxo_authorization_url(state=state, code_challenge=challenge))


def complete(value: str) -> None:
    saved = _load_state()
    if not saved.get("code_verifier"):
        raise SaxoConfigurationError("No pending PKCE authorization; run authorize first")
    parsed = urlparse(value)
    query = parse_qs(parsed.query) if parsed.query else {}
    code = (query.get("code") or [value])[0]
    returned_state = (query.get("state") or [""])[0]
    if returned_state and not secrets.compare_digest(returned_state, saved.get("state", "")):
        raise SaxoConfigurationError("OAuth state validation failed")
    adapter = SaxoSimAdapter.from_env()
    adapter.seed_authorization_code(
        code,
        code_verifier=saved["code_verifier"],
        redirect_uri=os.getenv("SAXO_REDIRECT_URI", "").strip(),
    )
    _state_path().unlink(missing_ok=True)
    summary = adapter.account_summary()
    print("SAXO_OAUTH_CONNECTED")
    print(f"account_probe=CONNECTED accounts={len(summary.accounts)}")
    print("portfolio_probe=CONNECTED")
    print("instrument_probe=CONNECTED")
    print("market_data_probe=CONNECTED")


def status() -> None:
    store = SaxoTokenStore()
    values = store.load()
    expires_at = float(values.get("expires_at", 0) or 0)
    remaining = max(int(expires_at - time.time()), 0) if expires_at else 0
    print(f"environment={os.getenv('SAXO_ENV', 'absent')}")
    print(f"client_configured={'yes' if os.getenv('SAXO_CLIENT_ID') else 'no'}")
    print(f"redirect_configured={'yes' if os.getenv('SAXO_REDIRECT_URI') else 'no'}")
    print(f"managed_token_present={'yes' if values.get('access_token') else 'no'}")
    print(f"refresh_token_present={'yes' if values.get('refresh_token') else 'no'}")
    print(f"token_health={store.health()}")
    print(f"expires_in={remaining}")
    print("last_refresh_status=UNKNOWN")


parser = argparse.ArgumentParser()
parser.add_argument("command", choices=("authorize", "complete", "status"))
parser.add_argument("value", nargs="?")
args = parser.parse_args()
_load_dotenv()
if args.command == "authorize":
    authorize()
elif args.command == "complete":
    if not args.value:
        parser.error("complete requires a redirect URL or authorization code")
    complete(args.value)
else:
    status()
