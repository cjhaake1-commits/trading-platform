# Bloomberg Research Connection and Benchmark Readiness

This integration is research-only. It does not submit orders, alter capital
allocations, or enable live trading.

## Supported Bloomberg connection paths

Bloomberg access requires an authorized Bloomberg subscription or enterprise
agreement plus the applicable exchange and dataset entitlements.

### Desktop API (DAPI)

Use DAPI on a Windows host that is running an authenticated Bloomberg Terminal
session. The common local endpoint is `127.0.0.1:8194`.

Do not configure DAPI directly on the Linux trading VM. Bloomberg's Linux API
libraries are intended for Server API and B-PIPE products, not a normal
Bloomberg Professional Terminal Desktop API session.

### Server API / B-PIPE

Use SAPI or B-PIPE on the Linux VM only after Bloomberg has provisioned the
licensed server-side product, network path, authentication mode, application
identity, entitlements, and any required TLS material.

Do not scrape Bloomberg screens, share Terminal credentials, or relay raw data
outside the rights granted by the applicable agreement.

## Installation

On the authorized Bloomberg host:

```bash
python -m pip install -r requirements-bloomberg.txt
```

Bloomberg publishes the Python package through its own package repository. The
core trading platform does not require this optional dependency.

## Configuration

Copy the Bloomberg section from `.env.example` into the host's uncommitted
`.env` and set only the values supplied or approved by Bloomberg.

DAPI example on an authorized Windows Terminal host:

```text
BLOOMBERG_ENABLED=true
BLOOMBERG_LICENSE_ACK=true
BLOOMBERG_RESEARCH_ONLY=true
BLOOMBERG_MODE=dapi
BLOOMBERG_HOST=127.0.0.1
BLOOMBERG_PORT=8194
```

SAPI example after Bloomberg provisioning:

```text
BLOOMBERG_ENABLED=true
BLOOMBERG_LICENSE_ACK=true
BLOOMBERG_RESEARCH_ONLY=true
BLOOMBERG_MODE=sapi
BLOOMBERG_HOST=<Bloomberg-provided-host>
BLOOMBERG_PORT=<Bloomberg-provided-port>
BLOOMBERG_AUTH_OPTIONS=<Bloomberg-approved-auth-options>
BLOOMBERG_APPLICATION_NAME=<Bloomberg-approved-application-name>
```

Do not guess SAPI authentication strings, endpoints, certificate paths, or
application names.

## Connection check

```bash
autotrader-bloomberg-check --show-config
```

To make an unavailable connection fail a deployment check:

```bash
autotrader-bloomberg-check --require-connected
```

The command prints non-secret status only. The hourly research refresh also
stores Bloomberg source health in the existing `provider_status` table.

## Data governance

Every Bloomberg-derived observation must preserve:

- source and service;
- Bloomberg security identifier;
- field name;
- provider timestamp and local receipt timestamp;
- entitlement/usage classification;
- transformation and feature version;
- downstream model and experiment identifiers;
- retention and redistribution restrictions.

Raw Bloomberg data must not be committed to GitHub or copied into unrestricted
training datasets. Derived features must remain within the rights granted by
the data agreement.

## Benchmark universe

`autotrader.benchmark_readiness.DEFAULT_BENCHMARKS` defines representative
comparators across:

- major US indexes;
- broad, growth, small-cap, global, bond, gold, and cash-like ETFs;
- common broad-market mutual-fund share classes;
- Bitcoin and Ether for the Crypto pillar.

The catalog carries both a public-data symbol and, where appropriate, a
Bloomberg security identifier. Benchmark membership is configurable and must be
reviewed before institutional use.

## What "consistently beating the market" means

The default paper-readiness policy requires at least:

- 126 observation days (roughly six trading months);
- 100 broker/provider-confirmed completed trades;
- three distinct market regimes;
- 95% data and benchmark coverage;
- realistic fees, spread, slippage, borrow/funding, and execution costs;
- verified accounting and complete data lineage;
- historical and synthetic stress tests;
- outperformance of at least 70% of the diversified benchmark set;
- outperformance of the rolling benchmark composite in at least 70% of a
  minimum 12 rolling windows;
- strategy maximum drawdown no greater than 20%;
- strategy drawdown no more than five percentage points worse than the median
  benchmark drawdown.

These thresholds are deliberately configurable through the
`LIVE_READINESS_*` environment values, but learning code must not lower them.
Policy changes require human review and a versioned governance record.

## Benchmark evidence command

The readiness command consumes normalized evidence from
`var/autotrader/benchmark-evidence.json` by default:

```bash
autotrader-benchmark-readiness
```

To use it as a strict paper-edge gate in CI or an operator checklist:

```bash
autotrader-benchmark-readiness --require-paper-edge
```

Expected evidence fields include observation days, completed trades, market
regimes, data coverage, net strategy return, drawdown, total and rolling
benchmark returns, benchmark drawdowns, and the accounting/cost/stress/lineage
verification flags. Missing evidence remains `LEARNING` or
`BLOCKED_DATA_INTEGRITY`; it is never treated as success.

## Live-capital boundary

A result of `PAPER_EDGE_CONFIRMED` does **not** enable live trading. It means the
paper system may proceed to a separate review covering:

1. human approval;
2. legal and compliance review;
3. independent risk review;
4. operational readiness and disaster recovery;
5. small-capital execution validation;
6. confirmation that live settings do not inherit aggressive paper settings.

The runtime currently rejects live mode. This branch does not change that
behavior.
