# Income-first $6,000 correction: rollout and research evidence

## Status of this patch

Prepared as an isolated review branch. Do not describe it as running on the VM. It restores source constants to $1,000 per pillar and adds read-only income-learning measurements. It does NOT migrate live SQLite ledgers, close positions, submit orders, enable leverage/options, reweight production strategies or complete the app freshness repair.

The last read of runtime-status still showed September 8, 2026 17:26:36 UTC, a $100,000 policy and no portfolio_accounting section. Deployment run 34260911534 for 4c6e31cd failed at Tests after changed-file lint succeeded; deployment was skipped. These are observations from the investigation, not permanent current-state assertions.

## Required before integration/deployment

1. Repair failing tests and restore adequate CI coverage; do not bypass validation to obtain a green deployment. Compare the complete deployed-to-target diff, not only the last commit.
2. Back up source and read a fresh provider/ledger reconciliation. Record account, position and pending-order ownership, current exposure, costs and equity. Existing $100k-scale exposure must not be forced into a $6k performance denominator.
3. Migrate only policy-dependent state transactionally. Preserve day-start equity, historical fills, IDs and prior cohorts. Record an explicit timestamped capital-policy change and cohort ID. Code constants alone are not a database migration.
4. If existing exposure/reservations exceed the restored economic envelope, report OVERALLOCATED_FOR_NEW_BASELINE and fail closed for new entries in the affected scope. Do not reset an account, fabricate a flat starting portfolio, close legacy/external/unknown inventory, or cancel protective exits. Normal risk management remains intact.
5. Start new $6k forward attribution only after reconciled eligible starting state exists. Old positions and $100k-period outcomes remain visible, but outside the $6k strategy-performance cohort. A separate isolated paper cohort may be required; no reset is authorized here.
6. Check every active sizing path, persisted baseline, app label and provider minimum. Economic starting capital is $6k; any signed retained net P&L and losses must be applied consistently. Shared Kalshi initial pool is $1k; shared Alpaca economic allocations sum to $3k, not three copies of its demo equity.
7. Repair the publisher's remote-branch synchronization safely. Direct remote workflow edits can leave its local worktree diverged; inspect evidence before claiming this is the cause. Never force-push, drop commits or stop publication merely to suppress CI alerts. Preserve sanitized data and do not expose credentials.
8. Wire outcome producers to the income-learning contract using genuine provider entry/exit records, reconciled cost-complete net P&L and the actual active capital-policy ID. Do not manufacture fields for old trades to fill a report.
9. Verify the deployed code version, fresh published accounting, all six pillar states, unsupported capability labels, app timestamp, one actual economic reconciliation and natural transaction progression when opportunity permits. A heartbeat cannot establish any of these on its own.

## Evidence input contract

The existing outcome ledger remains the storage system. New income reports require outcome_id; capital_policy_id=income-6000-v1; explicit PAPER/PRACTICE/SIM/DEMO mode; NATURAL origin; PLATFORM_OWNED classification; confirmed entry/exit flags plus provider order references; pillar, strategy and strategy_version; provider; timezone-aware entry/exit fill timestamps; positive allocated economic capital; nonnegative released capital; finite signed net_realized_pnl; and costs_complete=true.

Flags/references must come from reconciliation, not a prompt. This report is a learning measurement, not an independent broker audit. Complete accounts, open losses, outstanding obligations, settlement and operating expenses remain required before any income-withdrawal or promotion claim. Principal release is not profit; a linked subsequent entry is required before counting redeployment. Report insufficient evidence rather than zero gains or fabricated model improvement.

## Official sources checked September 8, 2026

- TradingAgents paper: https://arxiv.org/abs/2412.20138 . Supports multi-agent trading-firm research architecture; not a guarantee of profitable high-frequency scalping.
- Alpaca crypto spot capabilities: https://docs.alpaca.markets/us/docs/crypto-trading . Spot crypto is not marginable or shortable at this provider.
- Alpaca crypto fee schedule: https://docs.alpaca.markets/us/docs/crypto-fees . Published first volume tier is 0.15% maker / 0.25% taker per execution. Recheck actual tier and fees; two taker legs are approximately 0.50% before spread/slippage.
- Alpaca fractional trading: https://docs.alpaca.markets/us/docs/fractional-trading . Fractional short sales are not supported. Some text on this page conflicts with newer margin guidance; use current changelog and account capability evidence rather than blindly inheriting stale day-trade-count language.
- Alpaca margin: https://docs.alpaca.markets/us/docs/margin-and-short-selling . Equity margin/short eligibility has an account-equity minimum; collateral and per-asset requirements still apply. Demo balance is not proof of small-account eligibility.
- Alpaca current intraday margin migration: https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/ . Provider says it implemented the June 2026 replacement of PDT; do not hard-code an obsolete $25k restriction or infer that all providers migrated identically.
- Alpaca paper limitations: https://docs.alpaca.markets/us/docs/paper-trading . Paper results omit important latency, queue, market-impact and fee effects; conservative research overlays are needed, particularly for tiny-profit strategies.

These are research references and capability constraints, not proof that new market datasets have been downloaded, licensed, ingested or used to train the current model.
