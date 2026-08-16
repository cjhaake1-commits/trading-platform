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

We will wrap TradingAgents behind an adapter so market scanning, risk controls, paper/live execution, and broker integrations remain independent modules.

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

## Development stack

- Python 3.12
- VS Code on the VM
- GitHub for source control
- Codex for development/review support
- TradingAgents for multi-agent research

## Next milestone

Build the domain models, deterministic risk engine, paper broker, TradingAgents adapter, and unit tests.
