# Market Model Validation Lab

Two independent, reproducible studies for market risk, quantitative risk and model
validation interviews. Real observations support the research; independently
implemented checks, frozen protocols and explicit limitations support the conclusions.

**Start with the [report gallery](reports/index.html)**, then the [market risk
report](reports/market-risk/report.html) and [option pricing report](reports/options/report.html).
The [interactive evidence explorer](reports/evidence.html) lets you compare all
years, inspect event-day versus next-day risk, and hold the option quote cohort
fixed while changing rate assumptions and aggregation weights.
Each project includes an English validation report, management summary, Chinese
interview outline and a four-minute interactive walkthrough with a speaking script.

| Study | Question | Implementation |
|---|---|---|
| [Market risk](market-risk-validation/README.md) | Does a plausible forecast represent tail risk? | Fixed five-currency EUR cash book; historical simulation, EWMA Gaussian and joint EWMA FHS; 97.5% VaR/ES and 99% VaR |
| [Index option pricing](option-pricing-validation/README.md) | Is the implementation correct, and is its economic model adequate? | European PM-settled SPXW; analytic Black–Scholes/forward Black, independent CRR, QuantLib comparison, strike-group holdout and scenario repricing |

The numerical outputs and recorded verification results are in
[RESULTS.json](reports/RESULTS.json). Negative findings are retained. Non-rejection
is not a claim of model correctness or regulatory approval.

## Reproduce

Python **3.12** is the pinned study environment. From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .\market-risk-validation -e .\option-pricing-validation
.\.venv\Scripts\python.exe scripts\fetch_data.py --dataset all
.\.venv\Scripts\python.exe scripts\run_study.py
.\.venv\Scripts\python.exe scripts\verify_repo.py
.\.venv\Scripts\python.exe scripts\build_showcase.py
```

On macOS/Linux use `python3.12 -m venv .venv`, `.venv/bin/python`, and forward slashes.
The exact dependency versions are pinned, but package downloads are not hash-locked.
Each child package can also be installed and run independently; see its README.

Data acquisition is explicit. Later study runs use the local snapshots and do not
request live prices. The downloader reuses hash-verified cached files; a newly
downloaded source may differ if the provider revises its archive. Keep the recorded
snapshots to reproduce this particular study exactly. The option archive is about
239 MB compressed; unpacking, exclusions and frozen predictions need several GB of
free space. The full option study and formal simulation audit are substantial runs.

To run just one project, use `scripts/run_study.py --project market` or `--project
options`. `--skip-audit` omits the separate synthetic risk-validator audit; it does
not replace the formal audit required for the published gallery. The default risk
validation uses 5,000 resamples. Source/protocol hashes, commands, durations and
failure states are retained under `artifacts/private/executions/`.

For analysis or reporting changes that reuse already frozen predictions:

```powershell
.\.venv\Scripts\python.exe scripts\run_study.py --from-stage validate --skip-audit
.\.venv\Scripts\python.exe scripts\verify_repo.py
.\.venv\Scripts\python.exe scripts\build_showcase.py
```

The option flow now includes `diagnose` between `validate` and `report`. The
post-hoc diagnostics are independently reconstructed and leave original prices
and forecasts unchanged. `--from-stage report` rebuilds diagnostics/reports using
existing validated outputs. A changed validator or audit source requires a new
formal audit; publication rejects a stale audit, even when `--skip-audit` was used.

Execution records show the current step before it starts and retain live log
files. An interruption is recorded as `INTERRUPTED`, not success. Each verification
run immediately replaces the previous status with `RUNNING`; publication requires
a completed pass bound to the current code, tests and dependency versions. The
complete gallery is built privately and link-checked before replacing `reports/`;
failed builds leave the previous gallery intact, and previous bundles are retained
under `artifacts/private/publications/`.

For a local browser preview, run `python -m http.server 8765 --bind 127.0.0.1` from
the repository root and open `http://127.0.0.1:8765/reports/`. The four-minute demos
are silent HTML walkthroughs, with pause, next/previous and keyboard controls.

## Data and chronology

- **ECB FX:** 6,913 common observations, 1999-01-04 through 2025-12-31. Quotes are
  foreign units per EUR. Warm-up is 1999–2003, development 2004–2009 and evaluation
  2010–2025. Positions are fixed at inception; observed holidays are never filled
  with zero returns. Losses are reference-price hypothetical P&L.
- **Options:** the HistoricalData.net free 2022 H2 sample contains 127 daily files
  and 4,294,301 source rows. Only SPXW European PM-settled options with 30–180 days
  remaining enter the predefined filters. July–August develop the rules;
  September–December evaluate them. Call/put records at the same strike stay
  together. Daily calibration uses training strikes only; evaluation concerns
  contemporaneous withheld strikes, not a forecast of future quotes.
- **Rates:** 146 Federal Reserve H.15 DGS3MO observations via FRED. The most recent
  strictly prior observation provides an explicitly approximate flat discount
  input; a Treasury constant-maturity yield is not an OIS zero curve.

Missing quote times prevent a claim of synchronized option surfaces. A common
volatility can fail market checks even when the pricing software agrees with
QuantLib. Vendor IV/Greeks are never treated as independent truth.

See [data provenance](data/README.md), [data dictionary](docs/DATA_DICTIONARY.md), [sources](docs/SOURCES.md),
[data limitations](docs/DATA_AND_LIMITATIONS.md), and the
[review protocol](docs/REVIEW_PROTOCOL.md). Raw quotes and derived contract panels
remain local and ignored by Git under the vendor's redistribution restrictions.
Public artifacts contain code, acquisition instructions, provenance hashes and
aggregate research only. The MIT license applies to our code/documentation, not
third-party datasets.

## Verification

`scripts/verify_repo.py` runs dependency checks, lint and the offline test suites,
then records [summary.json](artifacts/verification/summary.json). Tests use local
fixtures and mocked downloads. The independent validators read frozen outputs;
they do not import the models to manufacture reference answers. The option
reference uses QuantLib. Fault-injection tests check leakage, understated tails,
clustered exceptions, excessive buffers and inconsistent evidence bundles.

The latest local run passed **141 tests**. Both studies' original frozen outputs
remain unchanged. See the [optimization review](docs/OPTIMIZATION.md),
[acceptance record](docs/ACCEPTANCE.md) and
[independent review and corrections](docs/INDEPENDENT_REVIEW.md).

The [formal synthetic audit](reports/market-risk/audit.md) separately measures
finite-sample rejection rates and uncertainty over 200 paths of 5,000 observations.
Its power estimates describe those simulated alternatives, not market performance.
An approximate ES bootstrap remains an approximate test.

GitHub Actions is configured for Python 3.12 on Windows and Ubuntu. Local
verification is recorded separately; a workflow definition does not imply that a
remote CI run has occurred. No live services or paid data are required by tests.

## Structure

```text
market-risk-validation/     Independent package, CLI, protocol and tests
option-pricing-validation/  Independent package, CLI, protocol and tests
scripts/                   Acquisition, orchestration, verification, publication
data/manifests/             Sources, hashes, acquisition and quality records
docs/                      Research conventions and review records
reports/                   Shareable aggregate reports and demonstrations
artifacts/verification/    Recorded local acceptance result
```

Research scope deliberately excludes Heston, American exercise, structured
products, transaction-cost simulation and production deployment. Extensions must
be introduced as a new study version; this inspected historical evaluation period
cannot be represented as a fresh untouched holdout after tuning.
