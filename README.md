# Autonomous Multi-Market Trading Platform

Safety-first trading platform built on top of the public `TauricResearch/TradingAgents` framework.

## Current status

**Bootstrap / paper-trading only. No live broker execution is enabled.**

The initial goal is to build and prove the architecture with simulated capital before any real-money integration.

## Core architecture

```text
Market data + scanners
        |
        v
TradingAgents research / portfolio rating
        |
        v
Normalized trade proposal
        |
        v
Deterministic risk engine
        |
   APPROVE / REJECT
        |
        v
Paper execution adapter
        |
        v
Portfolio + audit log
```

AI analysis never receives unrestricted authority over a brokerage account. All proposed trades must pass hard-coded risk and portfolio limits.

## Planned market sequence

1. US stocks and ETFs
2. Major crypto pairs
3. Major forex pairs
4. Futures
5. Options only after the base execution and risk engine are mature

## Foundation

The AI research layer is based on:

- https://github.com/TauricResearch/TradingAgents

We wrap TradingAgents behind an adapter so market scanning, risk controls, paper/live execution, and broker integrations remain independent modules.

## Initial safety defaults

- Live trading: disabled
- Leverage: disabled
- Short selling: disabled initially
- Risk per trade: max 0.5% of account equity
- Daily loss stop: 2%
- Weekly loss stop: 5%
- Max open positions: 3
- Every accepted entry must have an explicit stop/invalidation price
- Every decision is logged

## Bloomberg research connector

The repository contains an optional, licensed, research-only Bloomberg BLPAPI adapter. Bloomberg is disabled by default and requires an authorized Bloomberg subscription or enterprise agreement plus applicable data entitlements.

```bash
autotrader-bloomberg-check --show-config
```

See `docs/BLOOMBERG_AND_BENCHMARK_READINESS.md` before configuring Desktop API, Server API, or B-PIPE access. The Linux VM must not be treated as a Bloomberg Terminal Desktop API host.

## Paper benchmark readiness

The platform includes a diversified benchmark catalog spanning major indexes, broad and specialized ETFs, common broad-market mutual-fund comparators, and crypto hurdles. Paper evidence is evaluated with:

```bash
autotrader-benchmark-readiness
```

The default gate requires roughly six trading months, confirmed completed trades, multiple market regimes, realistic costs, stress-test survival, verified accounting/data lineage, rolling benchmark consistency, and bounded drawdown. A passing result is `PAPER_EDGE_CONFIRMED`; it never enables live trading and only permits a separate human, legal, risk, and operational review.

## Development stack

- Python 3.12
- VS Code on the VM
- GitHub for source control
- Codex for development/review support
- TradingAgents for multi-agent research

## Next milestone

Continue paper-data learning, benchmark attribution, stress testing, source governance, and institutional-quality auditability before any separately approved live-capital validation.
