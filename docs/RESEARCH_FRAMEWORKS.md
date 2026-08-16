# External Research Frameworks and Integration Priorities

This project should not assume that any public framework creates edge by itself. Public frameworks are research accelerators: they can improve experimentation quality, feature discovery, regime modeling, execution research, and reproducibility. Any candidate contribution must survive our own out-of-sample, walk-forward, cost-aware, latency-aware validation before it can influence execution.

## Priority 1: Microsoft Qlib + RD-Agent(Q)

Use Qlib primarily as a research and model-evaluation layer, not as the broker execution authority.

Potential contributions:
- factor discovery and factor-library management
- supervised ML and time-series forecasting baselines
- market-dynamics and concept-drift research
- portfolio construction and order-execution research
- reproducible train/validation/test workflows
- automated factor/model challenger generation through RD-Agent(Q)

Integration rule:
- exported signals/challengers enter our research registry
- they are evaluated against existing champion strategies
- no generated factor/model is trusted merely because Qlib or RD-Agent produced it
- live permissions and risk limits remain controlled by our deterministic runtime

## Priority 2: FinRL-X / FinRL

Use FinRL-X and classic FinRL as reinforcement-learning research environments and benchmarks.

Potential contributions:
- allocation and position-sizing challengers
- dynamic risk overlays
- market-environment simulation
- sequential decision-policy research
- transaction-cost/liquidity-aware experiments

RL agents must remain challengers until they pass walk-forward, regime, friction, tail-risk, and stability gates. They must never be allowed to self-relax platform risk limits.

## Priority 3: FinGPT

Use FinGPT-style components as alternative NLP/sentiment challengers rather than as direct execution agents.

Potential contributions:
- financial-news sentiment
- filings/report classification
- event extraction
- financial-domain language embeddings/features
- comparison against general-purpose LLM research signals

All NLP outputs must carry provenance, timestamp, confidence, and information-availability time to prevent lookahead.

## Priority 4: FinRobot / other finance-agent systems

Use finance-agent frameworks as research/tool-orchestration references and challenger systems. Their outputs must be converted into structured evidence and compared with TradingAgents rather than blindly combined.

## Priority 5: TradeMaster and specialized RL/HFT research

Use TradeMaster and associated research such as EarnHFT as sources of experiment designs, environment assumptions, features, and benchmark ideas. Do not assume research HFT results transfer to our retail-broker latency, feed, queue position, or fee structure.

## Proposed ensemble architecture

The platform should evolve toward independent specialist research lanes:

1. Fast deterministic scanner / microstructure features
2. TradingAgents multi-agent research context
3. Qlib supervised/factor models
4. RD-Agent factor/model challengers
5. FinRL-X RL allocation/risk challengers
6. FinGPT financial NLP sentiment/event features
7. Alternative-data/political/institutional context

A meta-layer compares each lane's incremental contribution by asset, session, regime, horizon, latency sensitivity, turnover, slippage, and drawdown. Correlated signals do not receive independent credit.

## Promotion gates

A new framework/model/factor can influence simulated allocation only after:
- data-license/provenance validation
- anti-lookahead validation
- reproducible tests
- walk-forward out-of-sample testing
- transaction-cost/slippage modeling
- regime and stress testing
- comparison with a simple baseline
- incremental contribution analysis versus current champion

Promotion to live remains a separate deployment decision and cannot be automatic.
