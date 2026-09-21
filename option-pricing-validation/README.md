# European Index Option Pricing Validation

An end-to-end model-validation study for European index vanilla options. It separates **implementation correctness**, **numerical approximation**, **input uncertainty**, and **economic model limitations**.

The package contains a BSM analytic implementation, an independent European CRR terminal-payoff engine, spot and forward Greeks, bracketed implied-volatility inversion, a frozen numerical experiment, a four-leg shock study, and a real SPXW daily quote application. QuantLib is an external code oracle; agreement with it does not prove that constant volatility describes the market.

## Run

Python 3.11+; no API credentials or paid data subscription are required. The repository's data acquisition process places the actual source CSVs under `../data/processed/options/` and historical DGS3MO annual-decimal rates in `../data/processed/rates.csv`.

```powershell
python -m pip install -e ".[dev]"
python -m option_validation ingest --output output/full-study
python -m option_validation run --output output/full-study
python -m option_validation validate --output output/full-study
python -m option_validation diagnose --output output/full-study
python -m option_validation report --output output/full-study
python -m pytest -q
python -m ruff check src tests
```

The equivalent installed CLI is `option-validation`. `run --numerical-only --output output/numerical` explicitly creates a numerical-only study; it never invents market observations. `run --reingest` explicitly replaces the prior input snapshot. `validate` returns a nonzero exit code for an unresolved check or unavailable QuantLib.

On the prepared Windows workspace, use `D:/Project/market-model-validation-lab/.venv/Scripts/python.exe`.

## Outputs

- `output/full-study/report.html`: standalone local report with static scientific charts; no CDN or web service.
- `VALIDATION_REPORT.md`, `MANAGEMENT_SUMMARY.md`, `INTERVIEW_NOTES_ZH.md`: detailed English validation, a management decision note, and Chinese interview notes.
- `results.json`: frozen numerical cases, synthetic shocks and held-out market summaries.
- `validation.json` and `validation_receipt.json`: independently recalculated checks and an integrity receipt.
- `diagnostics.json`, `diagnostics_validation.json` and its receipt: post-hoc fixed-cohort rate comparisons, date/group-weighted descriptions and independently reconstructed statistics.
- `report_receipt.json`: report/figure hashes bound to validated inputs, diagnostic assessment and reporting source code. Publication can reject old reports paired with a newer validation.
- `predictions.csv`: complete common-volatility prices under base/±100 bp discount assumptions. Base-rate held-out quotes also carry bid/ask IV intervals; training and sensitivity IV fields are explicitly not computed.
- `ingest_exclusions.csv`, `ingest_manifest.json`, `ingested_quotes.csv`, `groups.json`: every source exclusion, source SHA-256, accepted input, training/holdout membership, fitted parameter and parity inconsistency.

The full historical prediction and exclusion files are large; they remain local and are ignored by Git. The report is a compact view, not a replacement for those audit records.

## Post-hoc model-failure diagnostics

The original model, cleaning rules, split and predictions remain unchanged. After reviewing the initial results, the package adds descriptive diagnostics with an explicit `post_hoc_descriptive` classification:

- **Matched rate scenarios:** use the intersection of exact held-out quote IDs under base/−100 bp/+100 bp. Keep status strata fixed at the base rate; report alternative-status transitions separately. This removes the changing-membership problem in the original scenario-specific parity tables, which are retained as composition descriptions.
- **Multiple descriptive weightings:** quote-weighted means, equal-date means and equal-date/expiry-group means. They answer different questions; equal weighting does not create independent observations. No p-values or IID confidence intervals are added.
- **Explainable failure patterns:** call/put × moneyness signed error, daily MAE/coverage and paired date-level rate changes. The same historical predictions support these views; no volatility smile or filter is tuned to improve the score.

The forward and common volatility were already refitted under each original rate assumption. The paired comparison therefore describes a complete recalibrated scenario, **not** partial rho or a causal rate effect. `diagnose` independently checks all cohorts, strata, table inventories and displayed statistics. `report` creates diagnostics on first use; an existing stale diagnostic is rejected and must be regenerated explicitly with `diagnose`.

Publication should call `option_validation.report.load_report_receipt(output_path)` to verify the complete source/input/report chain, including every figure referenced in the HTML. A software `FAIL` still produces a negative report, with market diagnostics explicitly `NOT_PERFORMED_SOFTWARE_FAILURE`; successful publication remains a separate decision. See [the diagnostic JSON contract](docs/DIAGNOSTICS_SCHEMA.md) for fields, units and release checks.

## What is actually validated

1. **348 frozen numerical cases**: full-input analytic price/spot Greek comparisons with QuantLib, deterministic boundaries, IV conditioning, and CRR convergence on 72 regular-domain cases at 128–2048 steps.
2. **15 synthetic portfolio shocks**: full revaluation and delta/gamma/vega/theta approximation, with the full-revaluation P&L and Greek approximation independently checked against QuantLib.
3. **Real quote input discipline**: SPXW/E/PM, 30–180 days, K/S 0.8–1.2, positive uncrossed quotes, spread/mid at most 15%, strictly prior historical rate, explicit missing quote-time flags.
4. **Held-out strikes**: calls and puts share one hash assignment per date/expiry/strike. The forward and one common volatility use training quotes only. July–August 2022 is development; September–December follows the frozen protocol, with contemporaneous training-strike recalibration each day. This is not a future-price forecast.
5. **Independent frozen-result auditing**: the validator imports neither the pricing implementation nor the calibration code. It checks complete case inventories, file hashes, every prediction's common fitted parameters and source membership, training parity intervals, external prices/Greeks/IV endpoints, and every displayed held-out statistic. Adversarial regression tests cover per-contract IV substituted for held-out predictions, fabricated zero errors, missing numerical cases and stale reports.

## Boundaries

- SPXW's European PM convention is required. American equity/ETF options and AM-settled contracts are outside the experiment.
- The 3-month Treasury observation is a **flat discount proxy**, not an OIS or zero-coupon curve. ±100 bp sensitivity includes re-estimation of training forwards and volatility.
- Missing intraday timestamps mean even parity-compatible daily quotes are not proven synchronous. When training parity intervals do not intersect, a stable training median forward is retained as **exploratory**, with the conflict disclosed separately. Severe identification failures are rejected with reasons.
- Bid/ask implied volatilities are diagnostics, not predictive accuracy. Provider IV and Greeks are never used as a gold standard.
- No market-acceptance threshold is tuned after observing results. Poor constant-volatility fit is a legitimate model-validation finding.
- No Heston, American pricing, market-surface deployment, derivative VaR integration, trading strategy or observed hedging P&L is claimed.

The implemented rules preceded the first full execution; documentation and audit corrections followed it. The September–December results are a retrospective fixed-protocol evaluation, not a freshly untouched prospective holdout. See [the recorded protocol](docs/FROZEN_PROTOCOL.md) for numerical tolerances, data conventions, rejection policies and chronology.

Contract conventions: [Cboe SPX specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications). External implementation: [QuantLib European option tests](https://github.com/lballabio/QuantLib/blob/master/test-suite/europeanoption.cpp). Historical rate series: [FRED DGS3MO](https://fred.stlouisfed.org/series/DGS3MO).
