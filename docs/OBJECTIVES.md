# Trading Platform Objectives

## Controlling owner mandate - September 8, 2026

Build an **active, short-horizon income-trading system**, not a managed wealth portfolio. Continuously seek opportunities to deploy modest trading capital, close positions when the validated exit logic warrants it, release usable cash, and redeploy it into the next qualifying opportunity. Fractional quantities and sub-cent net gains are legitimate when executable and profitable after costs.

The initial economic test is **$6,000 total: $1,000 each for Stocks, Crypto, Forex, Metals, International, and one shared Kalshi pool**. Predictions and Perps must not each receive a separate $1,000 allocation. The authoritative code is `src/autotrader/capital_allocations.py`; provider demo balances and leveraged buying power are capacity constraints, not additional owner capital.

This mandate supersedes the previous $100,000 expansion and the previous dual income/long-term capital mandate. Long-term investment and ETF-like wealth accumulation are a separate future project. Historical source revisions remain in Git; do not relabel prior performance.

The $6,000 is initial capital, not a perpetual cap that prevents legitimate compounding. Reconciled retained net gains can increase economic equity; losses, costs, withdrawals, open losses and outstanding obligations reduce usable capital. Returning principal, short-sale proceeds, margin borrowing, deposits, simulated balance top-ups and unrealized gains are not realized trading income. No automatic funding from the owner's other businesses.

Everything remains PAPER/PRACTICE/SIM/DEMO. This document gives no permission to enable real-money trading, transfer real funds, buy data, change leverage caps, or reset provider accounts.

## Operating loop and capital activity

Data -> fresh candidate -> cost/latency-adjusted edge -> existing risk and account constraints -> reserved capital -> order -> provider ACK/fill -> position management -> exit fill -> net outcome and released capacity -> next eligible opportunity.

Favor productive capital use rather than passive holding by default. Measure approved opportunities missed, capital locked in positions, holding time, idle time, actual capital released and linked redeployments. Rank comparable validated opportunities using net expected profit, capital tied up, expected duration, liquidity and downside risk. Avoid unstable rankings caused by near-zero holding-time estimates.

Do not impose a mandatory trade count, utilization percentage or daily dollar return. Increased turnover is useful only when it improves net economics. A small gross gain below round-trip costs is not an opportunity. Do not close every green position regardless of exit costs, retain losing positions indefinitely to inflate realized win rate, or loosen risk to reach an income target. Time stops, invalidation exits, profit-taking and loss exits require the same evidence-based testing as entries.

## Income-focused research and learning

Research intraday momentum, opening-range breakouts, breakdowns, VWAP reversion/reclaim, mean reversion, relative strength, volatility expansion, event-driven trading, FX session strategies, liquid crypto intraday strategies, eligible equity short sales and cost-aware scalping. Liquidity provision, market making, options calls/puts, spreads and other methods remain research-only until venue support, account eligibility, data, sizing, execution and risk are proven. A listed strategy family is not an active strategy.

Use legally accessible, properly licensed and timestamped price/volume data; bid/ask spreads and order books where available; executable liquidity and fill/cancel/reject logs; volatility and cross-asset regimes; official news and macro/central-bank calendars; earnings; public SEC/institutional/political datasets; authorized social and alternative data; borrow availability; fee schedules; financing and funding; and peer-reviewed research. Publication and receipt timestamps must be retained to prevent look-ahead. Promotional trading content is a hypothesis source, not validated return evidence. Unavailable, delayed or unlicensed feeds remain explicitly unavailable.

Model both entry and exit costs, fee tiers, order-size minimums, lot/tick precision, partial fills, latency, queue position, adverse selection, inventory exposure, borrow and margin constraints. Apply realistic operating expenses for market data, compute and model inference. Do not deduct spread/slippage a second time when already embedded in actual fill-based P&L. Keep monetary calculations precise enough for sub-cent outcomes and cryptocurrency quantities.

Use chronological out-of-sample/walk-forward tests, cost and latency stress tests, and separate natural forward-paper evidence. Keep research, backtests, hypothetical missed trades, old-capital cohorts and provider/external inventory distinct. Report sample size, strategy version, capital cohort and data provenance. Compare candidates with incumbent strategies and a no-trade baseline. No automatic promotion based only on win rate, turnover or positive realized P&L while open losses grow.

## Role of TradingAgents

TradingAgents supplies multi-agent research, competing bullish/bearish analysis and risk discussion. It is not proof of sub-second execution or an income guarantee. Use deterministic code for time-sensitive scanning, order/risk checks and execution; invoke slower model analysis only where incremental value exceeds latency and inference cost. Compare TradingAgents-assisted decisions with deterministic baselines under identical costs and realistic capital.

## Margin, shorts and provider realism

Keep economic capital, notional exposure, posted margin, available buying power and maximum loss separate. Large notional exposure is not income and cannot be presented as additional deployed cash. Margin calls are risk failures, not an income technique. No martingale sizing or maximum-leverage default.

Account eligibility is checked at the real provider-account level, while all internal pillar budgets still apply. Shared provider capital must not be multiplied across pillars; unrelated accounts cannot be treated as one funding pool. A large provider demo account must not hide restrictions that the intended small live account would face. Confirm settlement, account/jurisdiction permissions, margin, borrow, asset and order-type capabilities with current official sources and account responses.

## Required app and learning measurements

Show source timestamp and freshness, initial capital, current economic equity, cost-based capital committed, margin, notional exposure, pending/reserved amounts, available-to-trade capacity, open positions, new entries, exit fills, realized gains AND losses, unrealized P&L, fees/financing, operating costs, net P&L, and per-pillar/strategy/provider breakdowns.

For income generation also show complete round trips, net expectancy per cycle, profitable/losing days, turnover defined without leverage inflation, average holding time, time from released capacity to linked redeployment, missed qualified opportunities, drawdown, downside/tail risk and settled withdrawable cash separately from reinvestable equity. Display all-cost estimates separately from provider-reconciled results. Unknown is not zero.

`income_learning.py` adds a read-only income contract and cost-labeled closed-cycle measurements to the existing LearningIngestor report. It does not train a model, connect new feeds, change order routing or promote a strategy. Producers must provide reconciled fill provenance, net costs and the new capital-policy/cohort identity before results qualify. The deployment and accounting reconciliation must be verified before the app is described as corrected.

Old 10-30%+ daily-return ambitions and income-dollar targets are not assumed achievable, guaranteed, training rewards or execution quotas. Paper success alone is not proof of live income.

## Release acceptance

See `docs/INCOME_TRADING_ROLLOUT.md`. A source commit or a fresh heartbeat is not evidence of deployed code, executed transactions, profitable turnover or an improved model.
