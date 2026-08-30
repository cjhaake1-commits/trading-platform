# Intelligence Learning Tree Runtime Verification

Date: 2026-08-30 15:51 UTC  
Branch: `bootstrap-paper-trading-core`  
Verified SHA: `884a9e73dbec379d3e8ec5f4678840ace9fdc2aa`

## Validation

- Complete test suite: **431 passed** (416 preflight baseline; fifteen intelligence/fusion/forward-evidence tests added or integrated).
- Ruff: passed.
- `compileall`: passed.
- `git diff --check`: passed.
- GitHub branch HEAD and local HEAD: `dfee0903e5178f616da9cc6be053af9418ce037d`.

## Runtime

`trading-platform-public-intelligence.service` is active after deployment. The existing paper runtime and Streamlit process were not restarted. The service has one collector process and its shutdown trace is the expected SIGINT from the controlled restart, not a restart loop.

The existing research database is `var/autotrader/research.db`. Post-deployment read-only verification found 1,162 durable research records, 156,655 research features, 42 `intelligence_fusion` records, 195 idempotent forward-outcome jobs, zero resolved outcomes (all horizons are future-dated), four hypotheses, one attribution row, and healthy orchestrator/SEC checkpoints. Database size was 26,451,968 bytes. The collector uses the existing Coinbase/Bluesky public-data stream and recurring bounded maintenance cadence.

## Safety and existing platform

- `verify_paper_safety.py`: safe, zero violations.
- `LIVE_TRADING_ENABLED`: false by enforced paper safety evidence.
- Real-money orders: 0.
- Streamlit: active, HTTP 200 on `http://127.0.0.1:8501/`.
- Paper runtime: active, one autonomous paper process.
- Streamlit process: one.
- Public-intelligence process: one.

## Intelligence coverage

The branch includes typed corporate and social intelligence snapshots, quantitative research components, SEC point-in-time filing normalization, amendment/content-hash versioning, configured research-universe identity records, corporate feature derivation, explicit cross-source fusion, and persistence through the existing `ResearchStore` Learning Tree backend. Fusion records carry `execution_authorized=false` and `broker_control=0`; the intelligence modules contain no order-placement interface.

SEC and other source availability remains governed by configured lawful endpoints and credentials. Missing sources remain unavailable/auth-required rather than being represented as zero-valued observations. Forward social, filing, and outcome coverage must continue accumulating before any hypothesis can be promoted.

## Limitations

The scheduler is active but SEC is currently `AUTH_REQUIRED` because `SEC_USER_AGENT` is not configured. The orchestrator provides recurring corporate/fusion maintenance, durable outcome scheduling, automatic hypothesis population, and conservative attribution gates; it does not claim complete historical SEC backfill, full multi-platform social authorization, outcome resolution before the relevant horizons, or validated economic expectancy. Those require source availability and forward evidence. No execution thresholds or risk controls were changed.
