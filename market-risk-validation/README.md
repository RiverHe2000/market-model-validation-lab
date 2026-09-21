# Market Risk Validation — a frozen FX cash-book study

Three transparent one-day VaR/ES models are compared on an unchanged five-currency
cash book. The project separates forecast generation from independent statistical
validation, retains unfavorable findings, and tests the validator with controlled
counterexamples. It is an educational model-validation study, not a trading system
or a claim of production or regulatory approval.

## Run

From this directory, install into the repository's isolated environment:

```powershell
..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
..\.venv\Scripts\python.exe -m market_risk ingest --input ..\data\processed\fx.csv --output output\canonical\fx.csv
..\.venv\Scripts\python.exe -m market_risk run --data output\canonical\fx.csv --output output\full-study
..\.venv\Scripts\python.exe -m market_risk validate --predictions output\full-study\predictions.csv --output output\full-study\validation.json --bootstrap-samples 5000
..\.venv\Scripts\python.exe -m market_risk report --predictions output\full-study\predictions.csv --validation output\full-study\validation.json --output output\full-study\report
..\.venv\Scripts\python.exe -m market_risk audit --preset formal --output output\validator-audit
..\.venv\Scripts\python.exe -m market_risk verify --predictions output\full-study\predictions.csv --validation output\full-study\validation.json --report output\full-study\report --audit output\validator-audit
..\.venv\Scripts\python.exe -m pytest
```

The console entry point `market-risk` provides the same commands. Data acquisition
is deliberately separate; the root `scripts/fetch_data.py` produces the standard
CSV. Ingest also accepts official ECB long CSV. The package never makes a network
request, and its tests use synthetic fixtures only.

## Economic and statistical scope

- EUR base, USD/GBP/JPY/CHF/AUD cash, EUR 1m equivalent each at the first 2004 observation; freeze foreign units, no rebalance or interest carry.
- 1999–2003 warm-up; 2004–2009 development; 2010–2025 held-out. The first HPL follows the construction day.
- Historical simulation with 1,000 preceding joint returns, EWMA Gaussian with lambda 0.94, and joint-vector EWMA filtered historical simulation.
- 97.5% VaR/ES and 99% VaR; exact cash HPL using simple returns of EUR prices 1/FX.
- Exact binomial coverage intervals/tests, Kupiec and Christoffersen diagnostics, conditional-permutation clustering inference, approximate Z2 block-bootstrap ES inference, Holm adjustment, proper FZ0 and pinball scores.
- Predeclared stress-year and signed CHF-event views, plus rolling 250-observation diagnostics.

See [the frozen protocol](docs/FROZEN_PROTOCOL.md) for timing, inference and acceptance
rules. The independent validator never imports the model or runner modules.

## Artifacts

`run` writes protocol.json, holdings.json, predictions.csv and run_manifest.json.
The manifest binds source data, model-source files, protocol, quantities and
prediction hashes. Validation rejects changed files and date/split/calendar
inconsistencies. These are reproducibility checks, not a digitally signed audit trail.

`validate` independently reconstructs inception cash allocations and daily HPL
from source FX and frozen foreign quantities, and verifies every model's historical
window. It writes validation.json (schema 2) and validation.receipt.json (schema 1).
The receipt binds the result bytes, run manifest, predictions and validator source;
reports reject modified conclusions, scores or stale code. It is an unsigned
consistency mechanism, not a digital signature or hostile-rewrite guarantee.

It also writes `validation.diagnostics.json` (schema 1), bound by hash to the
validation and its receipt. This post-review descriptive extension retains every
calendar year and replays the original CHF anchor plus the observed worst-loss
date in each original stress year, using 20 observed dates on either side. It adds
no hypothesis tests or model selection. The inspected test period is not a fresh
holdout. [The diagnostic review](docs/DIAGNOSTIC_REVIEW.md) defines each quantity
and explains what can and cannot be concluded.

`report` produces a complete English report.md,
a self-contained report.html with embedded figures, and standalone PNGs. It includes
a management interpretation and Chinese interview notes. No numerical performance
claims are stored in this README before the actual study is run.

The report includes annual exception/gap heatmaps and event response plots.
`report/data/` contains annual.csv, event_responses.csv, event_series.csv and
currency_hpl.csv for independent inspection. `report/receipt.json` binds the exact
MD, HTML, figures and CSV bytes to the validation, diagnostics and reporting code.
Publishing code can call `market_risk.reporting.load_report_receipt` to reject
stale display artifacts before copying them.

`audit` writes a clearly labeled synthetic audit.json and audit.md. Normal and
Student-t null controls measure finite-sample false-rejection rates, while heavy-tail
misspecification, clustered hits, ES-only understatement and 5x risk buffers probe
different failures. Rejection rates have binomial confidence intervals; a single
null realization is not required to pass every test.

`audit.receipt.json` binds the JSON/Markdown evidence to the current audit and
validator source. `market_risk.audit.load_audit_receipt` checks that binding.
The `verify` command checks frozen inputs and these evidence receipts without
rerunning forecasts, resampling or the formal simulation. Source changes require
actual regeneration of their affected artifacts; never replace a recorded hash
manually to make an old experiment appear current.

## Interpretation and limits

The book measures reference-rate hypothetical cash P&L. It excludes executable
prices, bid/ask, financing, liquidity horizons and derivatives. A larger risk buffer
can suppress exceptions while worsening FZ0. A passed VaR coverage test does not
validate ES. Z2 bootstrap inference is approximate and depends on VaR quality and
dependence assumptions. Sparse tails are reported as insufficient evidence, and
non-rejection is never labeled proof of a correct model.

CLI parameter overrides exist for explicit sensitivity research and small offline
fixtures. They change the frozen protocol hash. They must not be used to retune the
named held-out experiment after inspecting its results.

Sources: [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html),
[Acerbi–Szekely ES backtests](https://www.msci.com/resources/research/articles/2014/Research_Insight_Backtesting_Expected_Shortfall_December_2014.pdf),
[Patton–Ziegel–Chen FZ0](https://public.econ.duke.edu/~ap172/Patton_Ziegel_Chen_JoE_2019.pdf).
