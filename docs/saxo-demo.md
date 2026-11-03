# Saxo demo setup

The platform supports Saxo OpenAPI simulation mode through `src/saxo_demo.py`.

Set these environment variables in the local `.env` or deployment secret store:

```text
SAXO_ENV=sim
SAXO_APP_KEY=your_simulation_app_key
SAXO_APP_SECRET=your_simulation_app_secret
SAXO_REDIRECT_URI=http://localhost:8501
```

The client uses Saxo's simulation authorization and gateway endpoints. It rejects non-simulation environments, requires an explicit access token before account or market calls, and exposes account, positions, quotes, and paper-order methods. Never commit the App Secret or access token to Git.
