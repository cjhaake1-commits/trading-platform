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

## Important interpretation of "daily P&L"

Daily positive profit is a **business target, not a guaranteed system property**. The software must never manufacture trades simply to force daily activity. On days when expected edge is weak, preserving capital or making no trade is an acceptable and desirable outcome.

The engineering target is therefore:

> maximize risk-adjusted expected daily P&L and opportunity capture while keeping drawdowns, execution costs, slippage, and failure risk inside explicit limits.

## Risk posture: aggressive, not reckless

The initial $1,000 pilot should pursue growth aggressively **when measurable edge is present**, while treating capital preservation as a hard constraint rather than a suggestion.

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
- trading simply to meet a daily activity target
- ignoring spreads, slippage, financing, liquidity, correlation, or event risk
- allowing one position or one market to threaten the account
- relaxing daily/weekly circuit breakers because a signal appears attractive

The preferred behavior is **dynamic aggression**: risk capacity rises when signal quality, liquidity, execution quality, and recent strategy performance are strong, and falls when drawdown, volatility, correlation, spreads, uncertainty, or system-health risk increase.

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

1. survive and preserve capital
2. maintain reliable data and execution
3. produce positive expectancy after all costs
4. improve consistency of daily/weekly realized P&L
5. increase capital utilization only when edge is present
6. scale position size only after adequate evidence

Raw trade count, gross profit, and headline win rate are not primary objectives.

## Metrics

Track at minimum:

- realized P&L by day, week, month, strategy, asset class, and signal family
- unrealized P&L
- net P&L after fees, spread, financing, and estimated slippage
- average daily P&L
- percentage of profitable days
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

## Risk principle

More information and faster execution are useful only when they increase **net expected value after costs and risk**. The system must not increase leverage, trade frequency, or position size simply to create daily profit.
