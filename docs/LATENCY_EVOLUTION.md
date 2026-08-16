# Latency and Execution Evolution

## Objective

The platform should become **faster, more selective, and more execution-efficient over time** as it accumulates data and learns where latency materially affects P&L.

Learning does not automatically make code faster. Speed must be engineered, measured, and improved deliberately. The system therefore treats latency as a first-class performance metric alongside return, drawdown, slippage, and signal quality.

## Core principle

> Reduce decision and execution latency wherever doing so improves net expected value, without removing risk controls or sacrificing data integrity.

The goal is not institutional microsecond HFT. The goal is to become progressively more competitive at the time horizons accessible to our infrastructure by eliminating avoidable delay and reserving slow AI reasoning for situations where it adds enough value to justify the wait.

## Two-speed architecture

### Fast path

The fast path handles time-sensitive decisions and should contain no blocking LLM call.

```text
streaming market event
    -> timestamp
    -> in-memory state update
    -> incremental features
    -> fast strategy / opportunity score
    -> deterministic risk check
    -> broker adapter
    -> order acknowledgement / fill
```

Use for:

- quotes, trades, spreads, depth, volatility
- breakout / momentum / mean-reversion triggers
- precomputed macro/event risk flags
- cached news / alternative-data features
- stop, exit, reduce, and kill-switch logic

### Intelligence path

The slower path updates context asynchronously:

```text
news / filings / social / political / institutional / macro
    -> normalize
    -> entity resolution
    -> credibility / recency scoring
    -> TradingAgents or other deeper research
    -> cached structured context
    -> fast path consumes latest valid context
```

The order engine should not wait for deep research unless the strategy explicitly requires it and the measured holding horizon makes the delay acceptable.

## Latency telemetry

Record these timestamps for every signal and trade:

- source/exchange event timestamp
- local receive timestamp
- feature-ready timestamp
- signal timestamp
- risk-approved timestamp
- order-submit timestamp
- broker-acknowledgement timestamp
- fill timestamp

Calculate at minimum:

- feed latency
- parsing/normalization latency
- feature latency
- strategy latency
- risk-engine latency
- broker round-trip latency
- time-to-first-fill
- total event-to-fill latency

Track p50, p90, p95, p99, worst-case, and timeout/error rates by provider, strategy, broker, asset class, and market session.

## Continuous performance loop

The platform should continuously identify avoidable delay and propose improvements:

1. profile the slowest stages
2. determine whether the latency has measurable P&L impact
3. optimize the highest-value bottlenecks first
4. replay historical/live-captured event streams against the new implementation
5. compare latency, correctness, slippage, and simulated P&L
6. deploy only when the change preserves safety and improves measured performance

Examples of acceptable optimization targets:

- replace REST polling with persistent WebSocket/TCP streams
- incremental calculations instead of recomputing full indicators
- precompute static/reference features
- cache TradingAgents and alternative-data context
- keep live books and state in memory
- write audit/history asynchronously
- reduce unnecessary serialization/deserialization
- batch non-urgent data writes
- avoid duplicate provider calls
- prioritize symbols with active signals rather than treating every symbol equally
- move validated CPU-heavy hot-path calculations to faster implementations when profiling justifies it
- position infrastructure geographically closer to broker/data endpoints when measured network latency becomes material

## Strategy-aware latency budgets

Not every strategy needs the same speed.

Examples:

- stop/kill-switch response: fastest possible path
- order-book / short-horizon momentum: sub-second target where feeds and brokers support it
- ordinary intraday breakout: seconds may be acceptable
- news/event trading: seconds, with faster alerts prioritized
- TradingAgents research: may take longer and should generally operate ahead of or alongside the fast path
- long-term ETF allocation: latency is largely irrelevant compared with model quality and transaction cost

The platform should learn the maximum tolerable latency for each strategy by measuring how expected edge decays as simulated execution is delayed.

## Edge-decay testing

For every short-horizon strategy, backtest/replay performance at artificial delays such as:

- immediate baseline
- +100 ms
- +250 ms
- +500 ms
- +1 s
- +2 s
- +5 s
- +15 s

Measure how return, win rate, fill probability, slippage, and drawdown change. This tells us whether engineering another 200 ms of speed is valuable for that strategy or irrelevant.

## Smart opportunity prioritization

The system should devote compute and data bandwidth where the expected value is highest.

A candidate priority score may incorporate:

- expected edge
- edge decay rate
- liquidity
- spread
- event recency
- signal agreement
- available risk budget
- current compute/API cost
- expected holding time

High-decay opportunities receive the fastest deterministic path. Low-decay opportunities can wait for deeper intelligence.

## Safety boundary

Speed optimization may never bypass:

- stale-data checks
- broker health checks
- buying-power / margin checks
- portfolio-wide risk controls
- hard daily/weekly loss limits
- order-size limits
- kill-switch logic
- duplicate-order protection
- audit logging

Where necessary, these controls themselves should be optimized so they remain deterministic and fast rather than removed.

## Dashboard metrics

Expose live performance metrics including:

- current event-to-signal latency
- current signal-to-order latency
- current order-to-ack latency
- current order-to-fill latency
- p95 and p99 latency by broker/provider
- feed staleness
- dropped/reconnected streams
- strategy edge decay versus execution delay
- slippage versus expected quote
- P&L lost to estimated latency
- P&L gained after deployed performance optimizations

## Evolution target

As the platform matures, it should not merely learn **what to trade**. It should also learn:

- which information must be processed first
- which calculations should be precomputed
- which strategies require the fastest path
- which providers create bottlenecks
- which AI calls add enough value to justify their latency
- where infrastructure investment produces measurable additional edge

That makes execution speed an evidence-driven competitive capability rather than an arbitrary race for lower latency.
