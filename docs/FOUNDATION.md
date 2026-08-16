# Project Foundation

This trading platform is explicitly founded on two supplied Tauric Research artifacts:

1. **TradingAgents: Multi-Agents LLM Financial Trading Framework** (arXiv:2412.20138v7, 3 Jun 2025)
2. **TradingAgents source snapshot** at commit `a33fd4c0f134485a43553a2c23a63cb14adbd88f`

The three ZIP files supplied for this project are byte-identical copies of the same source snapshot, so the platform treats them as one canonical foundation.

## What we inherit from TradingAgents

The research paper models a trading organization with these main stages:

- Analyst Team: fundamental, sentiment, news, and technical analysts
- Researcher Team: bullish and bearish debate
- Trader: synthesizes the evidence into a trading decision
- Risk Management Team: risk-seeking, neutral, and conservative perspectives
- Fund Manager: final approval / adjustment before execution

The framework also emphasizes structured communication between agents rather than relying only on unstructured conversation histories.

## What our platform adds

TradingAgents is the **research and decision-intelligence layer**, not unrestricted execution authority.

Our platform adds a deterministic operating shell around it:

```text
real-time market feeds
        |
        v
fast scanners / quantitative filters
        |
        v
TradingAgents multi-agent analysis
        |
        v
normalized proposal
        |
        v
DETERMINISTIC RISK + PORTFOLIO ENGINE
        |
        v
paper broker -> shadow mode -> live broker adapters
        |
        v
audit database + monitoring + performance analytics
```

## Research principles we will preserve

### Specialized roles
We retain role specialization because the source framework separates technical, fundamental, news, sentiment, debate, trading, and risk functions.

### Structured state
We prefer typed / structured objects between components so long-running automation does not depend on fragile free-form message history.

### Multi-perspective debate
Bull/bear debate and multiple risk perspectives remain available for expensive, high-conviction candidates rather than being run indiscriminately on every instrument.

### Risk-adjusted evaluation
Backtests and paper trading will track at minimum:

- cumulative return
- annualized return
- Sharpe ratio
- maximum drawdown
- realized P/L
- win/loss statistics
- fees and estimated slippage

### No look-ahead bias
Historical tests must only expose information that would have been available at the decision timestamp.

## Important limitations from the source research

The paper's reported experiment is a short historical simulation, primarily across a small set of large technology stocks. It reports strong results, but the authors also note intensive LLM/tool usage and that longer backtesting is future work. We therefore treat the reported results as research evidence to reproduce and stress-test, not as expected live performance.

The paper identifies real-time feeds and live deployment as future work. Those are precisely the layers this repository is being built to add, while keeping execution behind deterministic safeguards.

## Source pinning policy

The `tradingagents` optional dependency is pinned to:

`a33fd4c0f134485a43553a2c23a63cb14adbd88f`

We will not silently track upstream `main`. Upstream changes will be reviewed, tested, and deliberately adopted.
