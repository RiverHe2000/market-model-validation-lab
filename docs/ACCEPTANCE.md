# Local acceptance record — 2026-09-20

## Optimization revision

The second review passed **141 local offline tests** (50 market risk, 59 options,
32 root/data/release tests), with zero failures, errors or skipped tests. Dependency
consistency and all lint checks passed. The test receipt binds the source, test,
configuration and dependency inventory; the gallery rejects stale evidence.

Both frozen studies were independently revalidated and their diagnostic reports
regenerated through the root orchestrator. This revision adds annual/event risk
diagnostics and fixed-cohort option comparisons without changing primary model
outputs. The formal 200-path validator audit was rerun, with unchanged measured
rejection rates. New descriptive analyses do not constitute a fresh statistical
holdout. Details are in [OPTIMIZATION.md](OPTIMIZATION.md).

Current execution receipts are retained locally under
`artifacts/private/executions/20260920T093848.620186Z/` (market) and
`artifacts/private/executions/20260920T094156.464833Z/` (options). The market command
used `--skip-audit` because the newly bound formal audit had already completed.

The current gallery file/link inventory is [PUBLISH_MANIFEST.json](../reports/PUBLISH_MANIFEST.json).
The publication and browser review record is
[publication.json](../artifacts/verification/publication.json).

## Initial implementation acceptance (historical record)

Both projects were executed end to end from the local licensed snapshots after
independent review. No live-price request was made by either study. This record
describes the local Windows/Python 3.12.0 environment; remote CI has not been run.

| Check | Recorded outcome |
|---|---|
| Dependency consistency and root/child lint | PASS |
| Offline regression suites | 96 passed; 0 failed, 0 errors, 0 skipped |
| Root market orchestrator | run → validate with 5,000 resamples → report: PASS |
| Root option orchestrator | ingest → run → QuantLib validate → report: PASS |
| Market forecast reproducibility | Identical prediction CSV SHA-256 after complete rerun |
| Option result reproducibility | Identical frozen results JSON SHA-256 after complete rerun, including references to ingested files, fitted groups and predictions |
| Formal risk-validator simulation | 200 paths × 5,000 observations; rejection-rate confidence intervals retained |
| Static gallery | 13 HTML pages; no missing local links or images |
| Browser review | Gallery, full report layouts, option management summary, demo next/start/pause and loaded CRR figure inspected |
| Public-file boundary | No raw data, contract panels, local output directories or virtual environment included in Git's public-file candidates |

Reproduction fingerprints:

- Market predictions: `4d3b8a83534f21a2cda221d7003eb8ca73185563c2e9a3b42fa802f6142e451a`.
- Option results: `269c41ea1595ce32f1f542dee27580371f8f0715a425ac06daea47b1db7a1673`.

The market reproduction took approximately 7 seconds. The option reproduction
took approximately 238 seconds (50 ingestion, 87 experiment, 93 independent
validation, 8 reporting), on this machine. These are observed timings, not
portable performance guarantees. The already completed formal synthetic audit
was retained, because neither its statistical functions nor its experiment
changed during the later integrity corrections.

Machine-readable acceptance is in
[`artifacts/verification/summary.json`](../artifacts/verification/summary.json),
publication checks in
[`artifacts/verification/publication.json`](../artifacts/verification/publication.json),
and shareable aggregate research in [`reports/RESULTS.json`](../reports/RESULTS.json).
Full command logs and pre-execution source/protocol snapshots are retained locally
under `artifacts/private/executions/20260920T091427.624760Z/` (options) and
`artifacts/private/executions/20260920T091540.140793Z/` (market).

Economic conclusions remain separate from software acceptance: the held-out
Gaussian 99% VaR coverage is rejected; FHS and HS are not rejected, which is not
proof of correctness. The constant-volatility option study has poor held-out
spread coverage and does not establish market-model adequacy. Nonsynchronous
quotes, the Treasury discount proxy and approximate ES inference remain explicit
limitations. The historical evaluation periods have now been inspected and must
not be reused as fresh prospective holdouts after tuning.

Delivered demonstrations are interactive, silent four-minute HTML walkthroughs
and corresponding speaking scripts, not narrated video recordings.
