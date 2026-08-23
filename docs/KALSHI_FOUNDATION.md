# Kalshi event-intelligence foundation

Kalshi is deliberately disabled by default. `KALSHI_ENABLED=false`,
`KALSHI_TRADING_ENABLED=false`, and `KALSHI_PAPER_CAPITAL=0` mean no runtime
job, capital reservation, order path, risk input, or learning promotion path
is active. The client is read-only and restricted to the Demo environment.

Activation sequence:

1. Research-only normalization and calibration.
2. Authenticated Demo read-only retrieval.
3. Demo shadow strategy and hypothetical hedges.
4. Executable Demo Pillar 6 with separately authorized capital.
5. Cross-pillar challenger feature tests.
6. Hedge challenger tests.

No phase may skip directly to live trading. Kalshi records must retain
`provider=kalshi`, `broker_control=false`, and `execution_enabled=false` until
an explicitly reviewed future activation.
