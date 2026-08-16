# $1,000 Live Pilot Plan

## Objective

When the platform is fully built, validated in backtesting, paper trading, and shadow mode, the first real-money pilot will start with **$1,000**.

The system has two simultaneous goals:

1. **Short-horizon engine:** pursue daily realized P&L opportunities through intraday equities, forex, and eventually crypto/futures where account structure, market access, liquidity, costs, and regulations permit.
2. **Long-horizon engine:** maintain an ETF-like diversified core that compounds capital over time and receives a share of retained profits from the active engine.

Daily profit is a target, not a guarantee. The platform must be allowed to make no trade when expected edge is inadequate.

## Pre-live graduation requirements

The $1,000 pilot does not begin until all of the following are satisfied:

- timestamp-correct backtests with fees, spread, and slippage
- continuous paper-trading service running reliably
- shadow mode using live data without sending real orders
- broker/data-feed health checks and reconnect behavior
- persistent portfolio and P&L ledger
- tested stop-loss, daily-loss, weekly-loss, and kill-switch logic
- broker/account rules encoded in the execution layer
- complete audit trail from signal to fill
- minimum sample-size and performance gates defined before results are viewed

## Week-one purpose

Week one is a **live execution validation experiment**, not an income test.

We will measure:

- starting and ending equity
- realized and unrealized net P&L
- gross P&L versus fees, spread, financing, and slippage
- maximum intraday and weekly drawdown
- number of trades and rejected trades
- win/loss distribution and expectancy
- latency from event -> signal -> order -> fill
- difference between expected and actual fill prices
- performance by asset class and strategy
- performance by signal family: technical, news, social, institutional, political/alternative data, TradingAgents
- system uptime and operational errors
- whether the active engine added value over simply holding the long-term benchmark allocation

## Initial capital architecture

With only $1,000, the system should avoid over-fragmenting capital. The capital allocator will support configurable buckets rather than hard-coding a permanent allocation.

A conservative starting research configuration is:

- **Core / long-term bucket:** 50%
- **Active trading bucket:** 40%
- **Cash / operational reserve:** 10%

These percentages are provisional and must be adjusted for broker minimums, account rules, transaction costs, instrument sizing, and the evidence from paper/shadow testing.

The active bucket may internally favor whichever market offers the best feasible opportunity for a $1,000 account rather than forcing simultaneous exposure to stocks, forex, and crypto.

## Compounding / self-capitalization

Profits are retained according to an explicit capital-allocation policy.

Example logic:

```text
net realized profit
      |
      +--> restore reserve if below target
      |
      +--> add a configured share to long-term core
      |
      +--> retain a configured share in active trading capital
```

Losses reduce risk capacity. Position size is never increased to recover losses.

## Week-one risk research defaults

Initial live-pilot defaults remain intentionally small until the account demonstrates stable execution:

- no leverage unless a later explicitly approved configuration allows it
- no unrestricted short selling
- per-trade risk budget measured as a small fraction of total equity
- hard daily and weekly loss circuit breakers
- maximum simultaneous positions
- mandatory stop/invalidation logic for active trades
- no averaging down solely because a position is losing
- global owner-visible kill switch

Exact percentages will be finalized from paper/shadow results and the broker/account structure before live activation.

## Decision after week one

Do not scale solely because week one is profitable.

After week one, classify the pilot as one of:

- **operational failure:** execution/data/reliability problems require correction
- **negative but valid sample:** continue at the same or lower size while gathering evidence
- **promising but insufficient sample:** continue unchanged; do not scale yet
- **meets pre-defined graduation criteria:** only then consider a small increase in active capital

Scaling must depend on a larger sample of risk-adjusted results, not one profitable week.
