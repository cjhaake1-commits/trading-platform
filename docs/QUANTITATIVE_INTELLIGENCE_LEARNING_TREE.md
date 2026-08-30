# Quantitative Intelligence Learning Tree

## Purpose

This document converts real, publicly documented quantitative-investing methods into a research-only extension of the paper-trading Learning Tree. Film/television references are treated only as prompts for independently verifiable methods; fictional conduct, material nonpublic information, manipulation, deception, hacking, or other improper information acquisition is excluded.

## Research principles

1. Hypothesis before model: every feature or strategy needs an economic/market-structure rationale.
2. Constituents before headline: inspect underlying exposures, concentration, leverage, refinancing, liquidity and correlation rather than trusting aggregate metrics.
3. Model-risk first: record assumptions and stress volatility, correlation, liquidity and regime changes.
4. Mosaic research: combine lawful public signals; no single weak signal becomes truth merely through aggregation.
5. Cross-sectional + time-series research: test both relative ranking and own-history signals where economically appropriate.
6. Multi-factor research: value, momentum, quality/defensive, carry, trend, mean reversion, liquidity and volatility are research families, not guaranteed alpha.
7. Point-in-time discipline: use information as it was available at the decision timestamp; revisions must not leak into historical tests.
8. Transaction-cost realism: spread, slippage, fees, borrow/funding and market impact belong in evaluation.
9. Out-of-sample degradation is expected: published/backtested premia may weaken materially out of sample.
10. Research does not execute: new ideas enter hypothesis -> reproduce -> backtest -> validate -> shadow -> forward paper -> scorecard -> governance.

## Public institutional methods researched

### AQR
Public AQR research describes systematic equity selection using measurable characteristics including profitability, momentum, quality, risk and sentiment, and extensive work on value, momentum, carry and defensive/quality styles across asset classes. AQR's public momentum methodology also illustrates liquidity/universe screening and ranking prior returns while excluding the most recent month. These are research templates, not copied proprietary strategies.

### Two Sigma / institutional scientific process
Use the publicly described scientific workflow as an organizational pattern: formulate hypotheses, acquire lawful data, engineer point-in-time features, test reproducibly, measure out of sample, and retain negative results.

### Citadel / systematic equity research
Use the publicly described combination of statistics, economics, computer science, structural/flow analysis and large datasets as a research taxonomy. No attempt is made to reproduce proprietary signals.

### Man Numeric / quantitative stock selection
Use public descriptions of systematic stock selection, portfolio/risk control, large datasets and machine learning as research categories. ML is subject to the same point-in-time, cost, robustness and forward-test gates as simpler models.

## Public data sources approved for research adapters

- SEC EDGAR: filings, company facts/XBRL, 10-K, 10-Q, 8-K, Form 4 and 13F where legally/publicly available.
- FRED/ALFRED: macroeconomic series and vintage-aware historical data; ALFRED/vintage concepts should be preferred for historical macro tests to reduce revision leakage.
- FINRA: published equity short-interest data and other public transparency datasets subject to applicable terms.
- Cboe: public options market statistics, put/call measures, volatility-market statistics and other permitted public data.
- Existing licensed/provider market data already used by the platform.

Every adapter must store source, observed_at, effective_at when known, retrieval timestamp, licensing/commercial-use status, and provenance.

## Learning Tree

MARKET DATA
- price, return, volume, volatility, liquidity, spread, microstructure

FUNDAMENTAL
- revenue, earnings, margins, cash flow, balance sheet, leverage, debt maturity/refinancing, valuation, estimate/reported divergence when lawful data exists

SYSTEMATIC FACTORS
- value
- momentum
- quality/defensive
- carry
- trend
- mean reversion
- relative strength
- volatility
- liquidity

STRUCTURAL / FLOW
- short interest
- options positioning proxies from permitted public statistics
- ETF/index flow/rebalance effects when data exists
- cross-market dislocation
- crowding/concentration proxies

MACRO
- rates/yield curve
- inflation
- employment
- growth
- credit/liquidity
- USD strength
- risk-on/risk-off regime
- release surprise only when consensus data is lawfully available

CONSTITUENT / HIDDEN-RISK LAYER (Big Short lesson)
- aggregate-versus-constituent divergence
- concentration
- leverage
- refinancing wall
- credit deterioration
- correlation clustering
- geographic/sector concentration
- consensus-versus-underlying divergence

MODEL-RISK / STRESS LAYER (Margin Call lesson)
- volatility shock
- correlation shock
- liquidity shock
- gap shock
- funding shock
- model assumption breach
- regime break
- VaR/expected-shortfall research where statistically appropriate

MOSAIC INTELLIGENCE (Billions lesson, lawful/public only)
- filings
- macro releases
- market/flow data
- short interest
- options statistics
- news/social only from approved/licensed sources
- public-official activity only where commercial use is explicitly approved
- cross-asset confirmation

QUANT RESEARCH
- hypothesis registry
- feature provenance
- factor exposure
- regression/cross-sectional tests
- clustering/regime classification
- anomaly detection
- ensemble/confluence
- ablation tests
- multiple-testing controls

EVIDENCE ENGINE
- economic rationale
- dataset/time boundary
- point-in-time availability
- train
- validation
- forward paper
- actual vs shadow separation
- transaction costs
- expectancy/profit factor
- drawdown/MFE/MAE
- regime performance
- robustness/sensitivity
- promote/watch/demote/disable

## Required anti-overfitting controls

- Never promote a feature because of one successful backtest.
- Keep train/validation/forward periods explicit.
- Use walk-forward evaluation.
- Record all tried hypotheses, including failures, to reduce researcher-selection bias.
- Correct for multiple comparisons where many features/strategies are tested.
- Prefer simple economically interpretable baselines before complex ML.
- Run ablation tests to determine whether a new feature adds incremental information beyond existing features.
- Compare performance after realistic costs.
- Require minimum sample/evidence classifications already used by the platform.

## Integration contract

New research enters as context/features only. It cannot bypass confluence, portfolio risk, current-fund ownership, execution gates or paper-only safety. A new source/feature begins EXPERIMENTAL and normally SHADOW. Promotion requires completed forward outcomes and evidence that the feature adds incremental information after costs and risk.

## Initial hypothesis backlog

1. Cross-sectional 12-1 momentum versus existing short-horizon momentum.
2. Value + momentum interaction for equities.
3. Quality/defensive overlay for stock selection.
4. FX carry combined with trend and crash-risk regime filter.
5. Commodity/metals carry/term-structure features when provider data permits.
6. Short-interest level/change as a contextual equity feature, not a standalone signal.
7. Options put/call and volatility statistics as market-regime context, not deterministic direction.
8. Yield-curve/inflation/growth/liquidity macro regime classifier using point-in-time/vintage-aware data.
9. Aggregate-versus-constituent deterioration detector for sectors/indices.
10. Correlation-break and volatility-shock model-risk detector.
11. Cross-pillar risk-on/risk-off confirmation with strict circularity prevention.
12. Feature-ablation framework measuring incremental expectancy/information contribution.

## Source notes

Public research consulted for this framework includes AQR systematic-equity and factor research, AQR carry/value/momentum publications, FRED API documentation, FINRA public short-interest documentation, and Cboe public market-statistics documentation. Public descriptions of institutional quantitative research are used only to derive general research-process patterns; no proprietary model or confidential information is claimed or reproduced.
