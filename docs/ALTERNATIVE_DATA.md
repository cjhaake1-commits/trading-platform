# Alternative Data Layer

The platform will support a separate alternative-data context layer for:

- licensed / terms-compliant news feeds
- licensed / terms-compliant social-media feeds and public posts
- public statements, speeches, hearings, press releases, and other media coverage
- public-official trading activity only when the intended use is legally and contractually authorized

## Why public-official transaction data is gated

Federal House and Senate financial-disclosure systems contain important public information, but the underlying federal disclosure regime restricts commercial use of Financial Disclosure Reports. Because this platform is intended to inform a for-profit trading system, raw House/Senate disclosure reports are **not enabled as a trading signal source by default**.

Any future connector for public-official transaction disclosures must pass a documented legal/licensing review before `commercial_use_authorized=true` can be set. The code enforces that guardrail by excluding unapproved `PUBLIC_OFFICIAL_ACTIVITY` observations from the combined market signal.

This does not prevent the broader news/social layer from monitoring public policy developments, official statements, public speeches, hearings, press conferences, or terms-compliant media coverage. Those sources remain subject to their own API, licensing, copyright, and platform terms.

## Signal flow

```text
licensed news feeds ------------------+
                                      |
licensed social/public-post feeds ----+--> normalize -> recency/confidence weighting
                                      |                     |
public statements / media coverage ---+                     v
                                                    AlternativeSignalContext
                                                             |
                                                             v
                                            TradingAgents research context
                                                             |
                                                             v
                                             deterministic fusion/risk layer
                                                             |
                                                             v
                                                  paper execution only
```

Public-official transaction activity has an additional gate:

```text
public-official transaction observation
                |
                v
   commercial-use authorization?
          /             \
        no               yes
        |                 |
     EXCLUDE           INCLUDE
```

## Time-decay rules

Alternative information loses value at different speeds. The initial configuration uses configurable exponential decay:

- social: 6-hour half-life
- news: 18-hour half-life
- public-official activity: 14-day half-life, only if legally authorized

These are research defaults, not assumed alpha. Backtests must determine whether each source adds out-of-sample value.

## Political / policy signals we can study without relying on raw transaction reports

Examples include:

- legislation affecting industries or companies
- committee hearings and investigations
- official press releases and public statements
- regulatory announcements
- fiscal / monetary policy commentary
- defense, energy, healthcare, technology, trade, and tax policy developments
- public social-media posts where collection and use complies with platform terms
- reputable media reporting about policy and public officials

## Modeling rules

1. Alternative signals never directly place trades.
2. Each item carries source type, timestamp, directional score, and confidence.
3. Recency decay prevents old social/news material from dominating current signals.
4. Source weights are configurable and must be validated out of sample.
5. The system logs included and excluded observations.
6. A high alternative-data score cannot bypass portfolio risk limits.
7. Public-official activity defaults to excluded unless authorization is explicit.
8. Backtests must use the observation/publication time actually available to the market, not a later corrected timestamp.

## Research objective

The goal is not to blindly copy public figures, news headlines, or social sentiment. The goal is to determine whether these sources improve risk-adjusted prediction when combined with price/volume signals and the TradingAgents multi-agent research layer.
