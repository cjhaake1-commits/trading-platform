# Social Market Intelligence

## Objective

Continuously measure public, lawfully accessible social attention around securities and use it as research context in the Learning Tree. The GameStop episode is the canonical stress case: social attention, short interest, options activity, price/volume, liquidity and market structure can interact reflexively. The system must detect that regime without assuming that social popularity predicts direction.

## Inputs

Subject to platform terms, API access and commercial-use authorization:
- Reddit
- X
- YouTube
- TikTok
- Facebook
- Instagram
- Stocktwits
- approved news/social providers

For each observation retain point-in-time provenance: platform, public author identifier, publish time, first-observed time, source ID/URL when permitted, text-derived ticker/entity mapping, sentiment, engagement, and licensing/commercial-use status.

## Influencer graph

Track public accounts whose securities commentary is measurably market-relevant. Do not equate follower count with predictive skill. Maintain separate measures for reach, finance relevance, historical attention impact, historical directional calibration, market-cap/liquidity context, and false-positive rate. Historical impact must be measured against timestamped subsequent market behavior, never assigned by reputation alone.

## GameStop-style detector

For every covered symbol calculate:
- mention level
- mention acceleration/velocity
- unique-author breadth
- cross-platform breadth
- engagement acceleration
- sentiment and sentiment change
- influencer participation
- ticker ambiguity confidence
- bot/coordinated/noise/manipulation-risk proxies
- price/volume confirmation
- volatility expansion
- short-interest context
- options-volume/put-call/volatility context where permitted
- borrow/crowding context where lawful data exists
- fundamental divergence

Create regimes such as NORMAL, ATTENTION_RISING, VIRAL, CROWDED, SQUEEZE_RISK, DISTRIBUTION_RISK and MANIPULATION_NOISE. These are research classifications, not buy/sell commands.

## Safety and research integrity

- Social signals never bypass deterministic risk or execution gates.
- No attempt to coordinate, promote, manipulate, impersonate, scrape prohibited private content, or obtain material nonpublic information.
- High social attention can increase risk as easily as opportunity.
- Detect concentrated authorship and suspicious amplification; reduce confidence rather than rewarding it.
- Separate attention prediction from return-direction prediction.
- Evaluate after spreads, slippage, volatility and gap risk.
- Preserve negative outcomes and false viral alerts.
- New social features start research/shadow-only.

## Learning questions

The Learning Tree should test, rather than assume:
1. Does social attention lead price/volume or merely follow it?
2. At what market-cap/liquidity levels is attention most consequential?
3. Does cross-platform confirmation outperform single-platform virality?
4. Which public influencers have repeatable attention impact after controlling for market conditions?
5. Is influencer impact directional or only volatility/volume predictive?
6. How does short interest interact with attention velocity?
7. Do options conditions improve squeeze-risk classification?
8. When does extreme positive sentiment become a contrarian/distribution signal?
9. Which regimes produce unacceptable gap/slippage risk despite apparent edge?
10. Does the feature add incremental forward expectancy after existing price, flow, fundamental and regime features are removed via ablation testing?

## Integration path

PUBLIC SOCIAL DATA -> ENTITY/TICKER RESOLUTION -> DEDUPLICATION -> AUTHENTICITY/NOISE FILTER -> ATTENTION/VELOCITY -> INFLUENCER GRAPH -> CROSS-PLATFORM CONFLUENCE -> MARKET/SHORT/OPTIONS/FUNDAMENTAL JOIN -> SOCIAL REGIME -> SHADOW FEATURE -> FORWARD SCORECARD -> GOVERNANCE.

This layer is complementary to the corporate-intelligence ingestion branch. Corporate filings describe the issuer; social intelligence describes changing public attention. The Learning Tree learns when the two agree, when they diverge, and whether that divergence has repeatable forward information.
