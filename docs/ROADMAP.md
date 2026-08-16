# Trading Platform Roadmap

## Phase 0 - Bootstrap

- [x] Create standalone repository
- [x] Define domain models
- [x] Add deterministic risk engine
- [x] Add paper broker
- [x] Add TradingAgents adapter boundary
- [x] Add core unit tests
- [ ] Add CI workflow
- [ ] Run tests on the VM

## Phase 1 - Market data and scanner

- [ ] Normalize symbols across stocks, crypto, and forex
- [ ] Add candle / quote interfaces
- [ ] Add first stock data adapter
- [ ] Add first crypto data adapter
- [ ] Add candidate scanner
- [ ] Log every candidate and rejected candidate

## Phase 2 - Strategy layer

- [ ] Momentum strategy
- [ ] Mean-reversion strategy
- [ ] Breakout strategy
- [ ] Standard strategy signal schema
- [ ] Walk-forward backtest harness
- [ ] Fees and slippage model

## Phase 3 - TradingAgents integration

- [ ] Pin an upstream TradingAgents version/commit
- [ ] Configure selected LLM provider
- [ ] Convert five-tier portfolio rating into normalized proposals
- [ ] Add confidence / disagreement handling
- [ ] Cache research results to control cost
- [ ] Add timeout/failure fallbacks

## Phase 4 - Portfolio and risk

- [ ] Position-level stops
- [ ] Daily / weekly circuit breakers
- [ ] Correlation and sector exposure limits
- [ ] Per-asset-class capital buckets
- [ ] Maximum gross exposure
- [ ] Emergency kill switch

## Phase 5 - Paper trading

- [ ] Persistent SQLite/Postgres portfolio ledger
- [ ] Market-hours scheduler
- [ ] Crypto 24/7 scheduler
- [ ] Real-time paper fills
- [ ] Daily performance report
- [ ] Dashboard

## Phase 6 - Shadow mode

- [ ] Live data, no live orders
- [ ] Compare theoretical vs executable fills
- [ ] Measure latency and slippage
- [ ] Require minimum sample size before graduation

## Phase 7 - Broker adapters

Potential adapters, after paper validation:

- Interactive Brokers for broad multi-asset coverage
- Coinbase for crypto
- Additional broker/exchange adapters only when needed

Every live adapter must implement the same restricted execution interface and must remain disabled by default.

## Phase 8 - Tiny live pilot

Only after explicit review of paper and shadow results:

- separate live credentials
- explicit `LIVE_TRADING_ENABLED=true`
- tiny capital allocation
- no leverage initially
- hard daily/weekly account stops
- owner-visible kill switch
- complete audit trail

## Graduation metrics

No phase advances solely because of a high short-term return. We evaluate:

- total net return after costs
- maximum drawdown
- profit factor
- average winner / loser
- Sharpe / Sortino-type risk metrics
- strategy stability across market regimes
- real-vs-simulated execution differences
- operational failure rate
- API / data-feed reliability
