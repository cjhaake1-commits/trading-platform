# Saxo SIM authentication required

Status: **USER ACTION REQUIRED**. The trading platform is configured for Saxo SIM, but no usable client configuration or token was found in the repository `.env`, expected user config, or token store. No secret values are included here.

The supported bootstrap script is [saxo_oauth_bootstrap.py](/home/cjhaake/trading-platform/scripts/saxo_oauth_bootstrap.py).

Safe sequence:

```bash
cd /home/cjhaake/trading-platform
PYTHONPATH=src .venv/bin/python scripts/saxo_oauth_bootstrap.py status
PYTHONPATH=src .venv/bin/python scripts/saxo_oauth_bootstrap.py authorize
```

Open the printed SIM authorization URL in a browser, authenticate interactively with the Saxo SIM account, and provide the resulting localhost redirect URL to:

```bash
PYTHONPATH=src .venv/bin/python scripts/saxo_oauth_bootstrap.py complete '<PASTE_REDIRECT_URL_LOCALLY>'
```

The client ID and redirect URI must be configured as `SAXO_CLIENT_ID` and `SAXO_REDIRECT_URI` in the user-managed environment. Tokens are stored outside the repository at `~/.local/share/trading-platform/saxo-sim-tokens.json` with restrictive permissions. Do not paste credentials or tokens into Git, logs, or this report.

Verify without printing secrets:

```bash
PYTHONPATH=src .venv/bin/python scripts/saxo_oauth_bootstrap.py status
```

Expected result is `environment=sim`, configured client/redirect, managed token present, and `token_health=CONNECTED`. Then rerun the International SIM connectivity/runtime check or restart only the trading-platform International/runtime publisher service. ACKNOWLEDGED orders must still be reconciled to provider FILLED quantities before economic execution is recorded.
