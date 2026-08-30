# Corporate Intelligence Ingestion V1

## Scope

Maintain a point-in-time research corpus for the union of:

- current S&P 500 constituents;
- current Nasdaq-listed operating companies/securities in the configured research universe;
- current Dow Jones Industrial Average constituents;
- issuers/underlyings relevant to the configured Cboe options research universe.

Membership sets overlap. Store one issuer/security record with multiple memberships rather than duplicating fundamentals.

Do not treat an index, exchange, or options venue as the source of issuer financial statements. For U.S. public issuers, SEC EDGAR is the primary authoritative filing source. Exchange/index/reference sources establish universe membership and security metadata. Issuer investor-relations sites are supplementary for shareholder letters, earnings releases, presentations and transcripts when publicly accessible and permitted.

## Continuous ingestion architecture

UNIVERSE REFRESH
-> symbol/security identity resolution
-> ticker-to-CIK mapping
-> SEC submissions refresh
-> filing accession discovery
-> Company Facts/XBRL refresh
-> filing metadata/document discovery
-> optional public IR correspondence discovery
-> normalization
-> immutable raw provenance
-> point-in-time feature snapshots
-> filing delta/anomaly extraction
-> Learning Tree research features
-> shadow/forward evidence only until promoted.

## SEC filing coverage

Prioritize:

- 10-K annual reports
- 10-Q quarterly reports
- 8-K current reports and earnings-related exhibits
- DEF 14A proxy statements
- Form 4 insider transactions
- 13F where relevant to institutional-ownership research
- registration/debt/material-event filings when a research hypothesis requires them.

Retain accession number, filing timestamp/date, period of report, form, primary document and source URL.

## Financial statement detail

Capture raw reported XBRL facts and then map them into research groups. Do not discard issuer-specific extension concepts merely because a canonical US-GAAP concept is absent.

Income statement examples:
- revenue/sales
- cost of revenue
- gross profit
- operating expenses
- operating income
- interest
- taxes
- net income
- EPS
- share count.

Balance-sheet examples:
- cash
- receivables
- inventory
- current assets
- PP&E
- goodwill/intangibles
- total assets
- accounts payable
- current liabilities
- short-term debt
- long-term debt
- total liabilities
- shareholder equity.

Cash-flow/capital-allocation examples:
- operating cash flow
- investing cash flow
- financing cash flow
- capex
- acquisitions
- buybacks
- dividends
- debt issuance/repayment.

Derived research metrics may include margins, growth, FCF, leverage, liquidity, working-capital changes, accruals, ROA/ROE/ROIC proxies, capex intensity, buyback intensity and debt/refinancing changes, but derived values must retain links to source facts.

## Corporate correspondence

Where public and permitted, ingest metadata/text/features from:

- shareholder letters
- earnings releases
- investor presentations
- annual-report narrative
- MD&A
- risk factors
- segment disclosures
- guidance
- capital-allocation commentary
- material 8-K exhibits.

Research extraction should track changes in wording and disclosures over time, but narrative/NLP outputs are hypotheses/features, not facts. Persist the source passage/document identity and timestamp.

## Point-in-time rules

A fact becomes available to research no earlier than its public filing/publication timestamp. Restatements and amended filings create new versions; they must not rewrite history. Macro and issuer revisions require vintage/version awareness. Backtests must reconstruct what the model could have known at the decision timestamp.

## Refresh cadence

- Universe/security reference: daily and on detected membership changes.
- SEC submissions: frequent bounded polling for active universe; use SEC fair-access guidance and caching.
- Company facts: refresh after new filing discovery and scheduled catch-up.
- Filing documents/IR correspondence: event-driven after new accession/publication plus periodic reconciliation.
- Full integrity reconciliation: daily.

The implementation must identify itself in SEC requests, use bounded concurrency/backoff/caching, avoid unnecessary repeated downloads, and honor SEC fair-access guidance.

## Storage layers

RAW: immutable source payload/document metadata and content hashes.
NORMALIZED: facts, filing metadata, universe membership, corporate-document metadata.
FEATURE: point-in-time derived features and deltas.
EVIDENCE: strategy/feature outcomes, ablation tests and forward results.

## Learning features

Examples:

- revenue/earnings/margin acceleration or deterioration
- cash conversion and FCF divergence
- capex acceleration/deceleration
- leverage/refinancing change
- inventory/receivable divergence versus sales
- segment-level divergence
- buyback/dividend/debt allocation changes
- guidance change
- risk-factor/disclosure change
- insider transaction context
- short-interest context
- options/volatility regime context
- aggregate index health versus constituent breadth/fundamental deterioration.

No feature bypasses portfolio risk, confluence, paper-only execution controls or forward-evidence governance.

## Important universe distinction

"Nasdaq" is ambiguous. The Nasdaq Stock Market contains thousands of listed securities, whereas Nasdaq-100 is an index. V1 should support explicit universe policies rather than silently equating them. Recommended policies:

- SP500
- DJIA
- NASDAQ_100
- NASDAQ_ALL_ELIGIBLE
- CBOE_OPTIONS_UNDERLYINGS
- UNION_CORE
- UNION_EXPANDED.

This allows the platform to scale ingestion without changing research semantics.
