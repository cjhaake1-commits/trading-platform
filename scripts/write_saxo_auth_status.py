#!/usr/bin/env python3
"""Write non-secret Saxo SIM readiness state."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    token = Path(os.getenv("SAXO_TOKEN_STORE", "~/.local/share/trading-platform/saxo-sim-tokens.json")).expanduser()
    configured = bool(os.getenv("SAXO_CLIENT_ID", "").strip() and os.getenv("SAXO_REDIRECT_URI", "").strip())
    token_present = token.exists()
    payload = {
        "environment": "SIM", "configured": configured, "token_present": token_present,
        "user_action_required": not (configured and token_present),
        "bootstrap_script": "scripts/saxo_oauth_bootstrap.py",
        "status_command": "PYTHONPATH=src .venv/bin/python scripts/saxo_oauth_bootstrap.py status",
        "authorization_required": not (configured and token_present),
        "last_checked_at": datetime.now(UTC).isoformat(),
    }
    destination = Path("var/autotrader/saxo-auth-required.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".saxo-auth-", dir=destination.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
