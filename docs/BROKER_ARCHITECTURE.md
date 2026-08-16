# Broker Architecture for the $1,000 Autonomous Pilot

## Design decision

The platform must remain broker-agnostic. Strategy, signal fusion, portfolio accounting, and deterministic risk controls live above the broker layer. Each broker implements the same restricted execution interface so capital can migrate later without rewriting the trading logic.

For the initial $1,000 pilot, broker selection should optimize for:

- official API support for automated trading
- stable paper/practice environment
- streaming market and order-state data
- small minimum trade sizes
- low per-trade friction
- fractional sizing where possible
- reliable authentication and reconnect behavior
- clear support for the instruments actually traded
- ability to enforce owner-defined risk limits independent of broker leverage

## Recommended staged execution stack

### Alpaca: U.S. equities / ETFs / crypto

Use Alpaca as the preferred small-account API venue for the U.S. securities and crypto portion of the pilot, subject to final account approval and current terms.

Reasons:

- API-first trading platform
- paper and live APIs use closely aligned interfaces
- U.S. stocks and ETFs
- fractional shares, useful for a $1,000 account
- crypto trading for extended/24-7 opportunity coverage
- persistent API-key style integration is operationally simpler than a broker requiring a fresh interactive authorization every trading day

The long-term ETF-like portfolio can also reside here during the early pilot if desired, avoiding an additional brokerage account solely for the core allocation.

### OANDA: forex

Use OANDA as the preferred first forex adapter for the small-account pilot, subject to final account approval and current terms.

Reasons:

- official REST and streaming APIs designed for automated trading
- live and practice environments
- variable FX sizing down to very small unit quantities
- broad major/minor currency coverage
- no need to use the broker's maximum permitted leverage

The platform's risk engine, not the broker's leverage ceiling, determines allowed notional exposure.

### Interactive Brokers Pro: global expansion / consolidation candidate

Build an IBKR adapter as the long-term global execution layer for equities, options, futures, currencies, bonds, and international markets.

IBKR is strategically attractive because of its broad global market access and mature APIs, but it is not automatically the cheapest or most capital-efficient venue for a $1,000 forex pilot. Current spot-currency minimum order sizes and per-order commission minimums can be large relative to a $1,000 account. API market-data subscriptions also have account-equity and subscription requirements.

Therefore:

- develop and paper-test IBKR connectivity early
- enable live IBKR execution only where product minimums and transaction costs make economic sense
- expand IBKR usage as account capital grows and the strategy set adds futures, international equities, options, and other products

### E*TRADE: secondary / backup adapter, not primary autonomous venue

E*TRADE remains useful because the owner already has a login and its developer platform supports personal applications, account data, market data, and equity/options order placement.

Do not make E*TRADE the primary autonomous execution venue for the first pilot because its documented OAuth lifecycle expires the access token at midnight U.S. Eastern time and requires a fresh login to obtain a new token. That creates a manual authentication dependency that conflicts with the goal of a continuously operating multi-session system.

Its developer documentation is also centered on equities/options rather than the full multi-market execution scope required by this project.

Use cases:

- sandbox/API development
- backup U.S. equity adapter
- manual/secondary brokerage if useful later
- not a required funded account for the initial pilot

## Capital architecture

Do not hard-code a permanent real-money split before paper/shadow results exist.

The live capital allocator should treat broker balances as one logical portfolio while respecting that cash cannot instantly move between custodians.

Example logical structure:

```text
MASTER PORTFOLIO
    |
    +-- Core long-term allocation
    |      -> ETF / diversified holdings
    |
    +-- Active equities / crypto allocation
    |      -> Alpaca adapter
    |
    +-- Active forex allocation
    |      -> OANDA adapter
    |
    +-- Future global / futures allocation
           -> IBKR adapter
```

With only $1,000, over-fragmentation is a real cost. Before live funding, the paper/shadow system must determine whether the expected incremental value of maintaining multiple funded venues exceeds the loss of capital flexibility created by splitting the account.

## Small-account constraints

### U.S. equities

A $1,000 securities account should initially assume no margin leverage. Broker and FINRA intraday-margin rules must be queried/configured explicitly. Cash-settlement constraints must be represented in the capital allocator so the system never assumes immediately reusable securities buying power that is not actually available.

### Forex

Forex may provide the most flexible notional sizing for the first active pilot, but leverage must be dynamically limited by:

- stop distance
- realized and implied volatility
- spread and liquidity
- signal confidence
- correlated exposure
- current daily/weekly drawdown
- event risk
- broker margin requirement

### Crypto

Treat crypto as a separate risk bucket. Availability outside equity-market hours is useful for capital utilization, but 24/7 availability does not justify continuous exposure.

## Unified broker interface

Every live broker adapter should implement at minimum:

```text
get_account_state()
get_buying_power()
get_positions()
get_open_orders()
get_quote_or_executable_price()
submit_order()
replace_order()
cancel_order()
stream_order_updates()
health_check()
```

The platform must never expose unrestricted broker methods directly to TradingAgents or other LLM components.

## Execution safety

Before every live order:

1. verify broker connection health
2. verify primary market-data freshness
3. compare independent/reference price with executable broker quote
4. verify account/broker buying power
5. verify settlement/margin constraints
6. recompute portfolio-wide risk
7. calculate allowed quantity
8. submit order through the restricted adapter
9. wait for acknowledgement / handle warnings
10. record fill, latency, slippage, and full decision provenance

## Funding recommendation

Do **not** fund a broker solely because an account/login already exists.

Funding happens only after:

- paper trading is stable
- live-data shadow mode is stable
- broker adapter passes integration tests
- authentication/reconnect behavior survives restart tests
- all order and kill-switch controls are validated
- the chosen $1,000 allocation is approved from observed paper/shadow economics

The initial live account(s) should be selected based on the strategies that actually demonstrate edge during validation, not brand familiarity.
