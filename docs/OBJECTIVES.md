# Trading Platform Objectives

## Primary operating objective

The platform is being designed to pursue **daily realized P&L opportunities** through short-horizon trading, with particular emphasis on:

- intraday U.S. stock and ETF trading
- liquid major forex pairs
- 24/7 crypto opportunities where appropriate
- fast reaction to price, volume, volatility, news, social, political, institutional, insider, and other authorized quantitative data
- TradingAgents multi-agent research as a deep-analysis layer for the best-ranked candidates
- deterministic risk, sizing, loss limits, execution controls, and auditability around every trade

The system should maximize the quality and speed of the information pipeline while minimizing unnecessary latency and expensive LLM calls.

## Role as an autonomous income pillar

This trading platform is intended to operate as a **standalone autonomous income and capital-growth pillar** alongside the owner's other automated businesses.

It has two complementary mandates:

1. **Active income engine:** continuously seek high-quality short-horizon opportunities across approved global markets and trading sessions, with daily realized P&L as the operating target.
2. **Long-term capital engine:** retain and compound capital through a diversified ETF-like portfolio and systematically allocate a share of realized profits toward long-horizon growth.

The trading pillar must remain financially and operationally isolated from the other business pillars. It may report performance into a shared command center, but operating cash from other businesses must not be automatically transferred into trading, and trading losses must not be funded automatically from other business accounts.

## Daily return ambition

The platform's **stretch performance bar is the ability to produce 20-30% positive days when genuine, unusually strong edge and market conditions make that achievable**. Engineering, research, market coverage, information acquisition, execution quality, capital utilization, and strategy discovery should all be optimized with that upper-end capability in mind.

A 20-30% return is **not a guaranteed daily result and not a quota that overrides risk controls**. The platform must never manufacture trades, chase losses, increase leverage merely because a daily target has not been reached, or reinterpret a lack of opportunity as a reason to relax validation.

The engineering objective is therefore:

> continuously improve the probability and magnitude of positive daily P&L, including the ability to capture exceptional 20-30% days when real edge exists, while keeping drawdowns, execution costs, slippage, and failure risk inside explicit limits.

The dashboard should track progress toward 10%, 20%, and 30% daily return thresholds, but the risk engine remains independent of those thresholds. Missing a threshold is diagnostic information, not an execution signal.

## Continuous intelligence and evolution mandate

The platform must operate as a learning system rather than a static strategy bundle.

It should continuously:

- monitor approved market, news, macro, social, political, institutional, insider, derivatives, microstructure, and alternative-data sources
- timestamp and normalize incoming information into a common feature model
- measure latency, reliability, cost, and freshness for every provider
- attribute realized and unrealized P&L to strategies, signals, data sources, asset classes, market sessions, and execution venues
- detect when a previously useful signal is decaying or failing in a new regime
- discover candidate new features and combinations from accumulated data
- re-estimate signal usefulness using timestamp-correct historical and recent out-of-sample evidence
- compare fast deterministic strategies with TradingAgents-assisted decisions
- maintain market/session-specific models rather than assuming one strategy works everywhere
- identify gaps in the information base and evaluate additional legitimate APIs or datasets
- continuously improve execution routing, capital utilization, and data-processing latency

No data source or model receives permanent trust. Its weight must be earned and re-earned through evidence.

The system may automate measurement, ranking, parameter research, and candidate-model generation, but **live risk limits and execution permissions may not self-relax without passing predefined validation and deployment gates**.

## Risk posture: aggressive, not reckless

The initial pilot should pursue growth aggressively **when measurable edge is present**, while treating capital preservation as a hard constraint rather than a suggestion.

Aggressive means:

- scan broadly across approved markets and global sessions
- recycle available capital into multiple independent high-quality opportunities
- use controlled notional leverage where the instrument, broker, liquidity, and tested strategy support it
- favor the strongest risk-adjusted expected-return opportunities rather than leaving capital idle by default
- react quickly to validated market, news, social, political, institutional, and alternative-data events
- compound retained profits and increase usable trading capital as the account grows

Aggressive does **not** mean:

- maximum broker leverage
- increasing size after losses to recover money
- trading simply to meet a daily activity or return target
- ignoring spreads, slippage, financing, liquidity, correlation, or event risk
- allowing one position or one market to threaten the account
- relaxing daily/weekly circuit breakers because a signal appears attractive

The preferred behavior is **dynamic aggression**: risk capacity rises when signal quality, liquidity, execution quality, and validated strategy performance are strong, and falls when drawdown, volatility, correlation, spreads, uncertainty, or system-health risk increase.

## Information advantage

The platform should seek the broadest legitimate information base that can be tested and maintained reliably:

1. price, volume, spreads, volatility, order/market microstructure where available
2. technical and statistical indicators
3. market regime and cross-asset relationships
4. company fundamentals and earnings information
5. real-time and historical news
6. social-media sentiment and velocity
7. government policy, hearings, legislation, contracts, lobbying, and political exposure
8. authorized congressional/public-official transaction datasets
9. SEC Form 4 insider activity
10. institutional and 13F ownership changes
11. off-exchange / dark-pool indicators
12. options/futures positioning where licensed data is available
13. macroeconomic and central-bank events
14. additional alternative datasets only after data rights, timestamp integrity, and backtestability are verified

No information source receives permanent weight merely because it is interesting. Each feature must demonstrate incremental predictive value in timestamp-correct backtests and paper/shadow trading.

## Speed architecture

The intended decision pipeline is:

```text
high-speed feeds
    -> deterministic universe scanner
    -> feature calculation / event detection
    -> rank candidates
    -> fast baseline strategies
    -> alternative-data fusion
    -> TradingAgents deep research only for top candidates
    -> deterministic portfolio/risk approval
    -> execution adapter
    -> fill / P&L / attribution logging
```

Fast deterministic code should handle continuous scanning. Slower multi-agent LLM analysis should be reserved for situations where its expected value exceeds its latency and API cost.

## Daily operating modes

### U.S. equities
- pre-market preparation and ranking
- opening-session opportunities
- intraday momentum / breakout / mean-reversion opportunities
- event-driven repricing
- close/overnight-risk decisions

### Forex
- continuous session-aware monitoring
- Asia / London / New York session context
- macro-event and central-bank awareness
- spread and liquidity filters

### Crypto
- continuous monitoring
- separate risk bucket from equities/forex
- 24/7 scheduler and health monitoring

## Performance hierarchy

The platform should optimize in this order:

1. maintain reliable data and execution
2. produce positive expectancy after all costs
3. preserve enough capital to continue exploiting edge
4. improve consistency and magnitude of daily/weekly realized P&L
5. increase capital utilization when measured net edge is present
6. capture exceptional-return opportunities when evidence supports them
7. scale position size only after adequate evidence

Raw trade count, gross profit, and headline win rate are not primary objectives.

## Metrics

Track at minimum:

- realized P&L by day, week, month, strategy, asset class, and signal family
- unrealized P&L
- net P&L after fees, spread, financing, and estimated slippage
- average daily P&L
- percentage of profitable days
- frequency and conditions of 10%, 20%, and 30%+ return days
- best / worst day
- maximum daily and rolling drawdown
- Sharpe / Sortino-like risk-adjusted measures
- profit factor
- expectancy per trade
- average win / loss
- tail loss statistics
- latency from event -> signal -> decision -> order -> fill
- opportunity rejection reasons
- P&L attribution by information source
- incremental value of TradingAgents versus deterministic baselines
- feature decay / drift statistics
- provider latency, freshness, uptime, and cost-to-edge contribution
- latency-adjusted expected edge before every new exposure decision
- stressed performance under higher slippage, costs, latency, and adverse regimes

## Risk principle

More information and faster execution are useful only when they increase **net expected value after costs and risk**. The system must not increase leverage, trade frequency, or position size simply to create daily profit.
