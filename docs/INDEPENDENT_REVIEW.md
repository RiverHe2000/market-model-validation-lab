# Independent implementation review

This section records the first implementation review. The subsequent optimization
review added descriptive diagnostics, source-bound evidence, uninterrupted logs
and staged gallery replacement; see [OPTIMIZATION.md](OPTIMIZATION.md) and the
current [acceptance record](ACCEPTANCE.md). The formal audit was rerun in that
later revision; statements below about retaining the earlier audit describe the
first review only.

Review date: 2026-09-20. Scope: the FX market-risk and European index-option studies, their validators, and report generation. This review used read-only inspection of product code and controlled reproductions in temporary directories. It did not change either implementation or the frozen research outputs.

The findings below preserve the implementation behavior and pending status **at the initial review**. Subsequent owner corrections and regression closure are recorded in the final section. Reproduction descriptions contain no vendor quote rows or machine-specific paths.

## Meaning and limits of the integrity controls

SHA-256 checks can establish that a file still matches the bytes recorded in a manifest. An unsigned manifest is an integrity receipt, not a digital signature, an independent trust anchor, or proof that a computation is correct. Someone able to rewrite both a file and its manifest can replace both consistently. Source hashes also do not establish market-data accuracy or synchronized quotes.

Several tests below deliberately update output hashes after introducing a defect. This simulates a faulty producer generating a self-consistent frozen result; it tests the independent validator's economic and structural checks. It is not a claim that a hash should detect a coordinated replacement of its own reference value.

Report integrity has a separate boundary: a report should check that the statistical results and input artifacts it displays are the same artifacts validated earlier. A receipt for validation results and the validator's source identity helps detect accidental changes or stale results, but remains unsigned consistency evidence.

## Option-pricing findings

### O1 — Per-contract IV can masquerade as held-out common-volatility predictions

**Status:** reproduced; awaiting owner regression check. **Impact:** high.

The market validator independently checked prices with QuantLib, but did not bind each prediction's forward, discount factor, time, sigma, rate shift and status to its unique fitted date/expiry/rate-shift group. Thus a correct Black price under the wrong, holdout-derived parameters could pass.

Reproduction:

1. Generate a synthetic smile with 49 strikes from 3,400 to 4,600, calls and puts, a forward of 4,000, 90/365 maturity, and positive two-sided quotes. Use the existing deterministic paired-strike assignment and common-sigma training fit.
2. The fitted common sigma was approximately 0.22664023; held-out bid/ask coverage was 0%. The independent validator returned `PASS` with no failures.
3. Leave the fitted group and its training evidence unchanged. Replace each holdout prediction's sigma with its own midpoint-implied volatility, approximately 0.19–0.30; set its model price to the observed midpoint and recompute its errors, summaries and output hash.
4. Coverage became 100%, yet validation still returned `PASS` with no failures.

Required regression: reject any row whose parameters or membership disagree with its unique frozen group; check prediction-key completeness and uniqueness, not only the rows present. Independently reconstruct training parity interval bounds rather than trusting stored bounds used to clip the forward estimate.

### O2 — Report accepted a group file changed after validation

**Status:** reproduced; awaiting owner regression check. **Impact:** high.

After a normal numerical run and successful validation, replace `groups.json` with a synthetic rejected group carrying a distinctive reason. Keep `results.json` unchanged. Report generation succeeded and displayed the injected group reason.

The report checked the validation receipt's `results.json` hash but did not recheck all artifact hashes referenced by those results. Required regression: changing any frozen group, prediction or ingestion artifact after validation must prevent report generation until validation is repeated.

### O3 — Reported error statistics were not independently reconstructed

**Status:** observed in validator code and exercised as part of O1; awaiting a dedicated owner regression check. **Impact:** high.

The validator reconstructed overall coverage and quote counts, but did not reconstruct every prediction's error, absolute error and spread-scaled error, or the reported MAE/RMSE. It skipped moneyness-band summaries. O1's substituted errors and aggregate results were accepted, demonstrating that the parameter-binding defect could propagate into reported performance.

Required regression: preserve correctly priced predictions but replace error fields and reported MAE/RMSE with incorrect values; validation must reject the inconsistency. Reconstruct each reported summary, including moneyness bands and expected summary-key coverage. A valid pricing oracle alone does not verify the statistics subsequently reported.

### O4 — Removing all numerical cases still produced software PASS

**Status:** reproduced; awaiting owner regression check. **Impact:** high.

Run the numerical-only study, which produced 348 numerical cases. Replace `results["numerical"]` with an empty list while retaining the shock experiment. Validation returned `software_validation="PASS"`, `numerical_cases_checked=0`, and an empty failure list.

Required regression: independently check the predeclared numerical case IDs, parameters, uniqueness and required CRR step sets. Empty or incomplete evidence must not silently become a software-validation pass.

## Market-risk findings

### M1 — Realized HPL was not reconstructed from source prices and holdings

**Status:** reproduced; awaiting owner regression check. **Impact:** high.

Using real ECB inputs with a short 2004 study, multiply every model's `pnl_eur` and `loss_eur` by 100, preserve their opposite signs, and update only the prediction file's hash in the run manifest. Leave source FX, holdings, model code and protocol unchanged. `load_frozen_predictions` accepted the file.

Agreement across model rows and a valid loss sign establish internal consistency, not correct EUR units or realized cash-book P&L. Required regression: independently reconstruct inception foreign units and gross notional, then recompute every dated HPL from the frozen units and reciprocal FX prices. This check must not call the forecast engine.

### M2 — Report accepted altered statistical conclusions

**Status:** reproduced; awaiting owner regression check. **Impact:** high.

Run `validate_file` normally. Change the development-selected model's test assessment in `validation.json` to a distinctive injected approval string and change its FZ0 mean to −9,999. Leave prediction and protocol hashes unchanged. Report generation succeeded and displayed the altered conclusion.

Required regression: record and check the validation result's integrity receipt and validator source identity; reject changed or stale statistical artifacts before rendering the report. Apply the unsigned-hash limitations described above.

### M3 — Historical-window metadata was checked only for the first model on each date

**Status:** reproduced; awaiting owner regression check. **Impact:** moderate.

Set every `ewma_gaussian` row's `history_start` equal to its `as_of`, update the prediction hash, and retain the other models' correct windows. The loader accepted the file. Its calendar-window check operated on `drop_duplicates("date")`, while cross-model comparability omitted `history_start`.

Required regression: check the complete source-calendar window for every date/model row, or first require identical window metadata across models and then verify that shared window.

## Checks that held up during review

- Removing an entire model was rejected even after updating the prediction hash and row count: the model set differed from the frozen protocol.
- Removing a complete forecast date across all models was rejected after updating the hash and row count: dates no longer covered the frozen source calendar.
- A direct future-data perturbation showed no material look-ahead effect. Multiplying CHF quotes dated 2004-07-01 and later by 1.05 changed earlier forecasts, including the forecast for the first changed day, by at most **4.8 × 10⁻¹⁰ EUR**. Earlier realized HPL changed by at most **3.1 × 10⁻¹⁰ EUR**. These differences are consistent with CSV floating-point round trips. The comparison excluded provenance hashes, which should change when source bytes change.
- With actual ECB quotes, inception foreign units divided by the inception quote gave EUR 1 million for each currency, within floating-point precision. Independently reconstructing the first realized HPL from reciprocal quotes produced **zero recorded error**.
- The actual canonical FX source contained no weekend observations. Its maximum interval between observed dates was five calendar days. The study advances by observed reference-rate dates and does not insert holiday rows; this is an observation-to-observation horizon, not a guarantee of 24 elapsed hours.

These are bounded checks of the reviewed implementation and supplied data, not proof of universal correctness or production suitability.

## Actual source-data verification

The downloader was run against real, freely accessible sources, then rerun from its hash-verified cache. No provider Python was executed.

| Input | Actual verified scope | Key boundary |
|---|---|---|
| ECB foreign-currency-per-EUR reference rates | 6,913 common dates, 1999-01-04 through 2025-12-31, USD/GBP/JPY/CHF/AUD | Original official ZIP and wide CSV retained; normalized long CSV explicitly identified as derived; no interpolation |
| Federal Reserve H.15 / FRED DGS3MO | 146 observed dates, June–December 2022 | Percent divided by 100; holiday missing values omitted; a three-month investment-basis yield is a discount proxy, not an OIS/zero curve |
| HistoricalData.net options sample | 127 dates, 4,294,301 rows, 2022-07-01 through 2022-12-30 | Complete publisher file-list, SHA-256, byte and row checks; schema and encoded contract-field consistency verified independently |

All 2022 option quote timestamps were absent. Five dates had differing SPX and SPXW underlying closes, with a maximum difference of 3.05 index points. The archive contained 1,531,527 two-sided, uncrossed SPXW European PM-settled rows before study-specific maturity and moneyness filters. These counts establish available inputs, not synchronized quote quality or independent samples.

Raw inputs and per-contract outputs remain local and ignored by Git. Public repository evidence should contain code, methodology, aggregate diagnostics and provenance, not reconstructable vendor quotes. The download component's 19 offline integrity/schema tests and Ruff checks passed at review completion.

## Regression closure — 2026-09-20

The final local suites pass all **96 tests**: 37 market-risk, 40 option-pricing and
19 acquisition tests. The named tests below exercise the observed defects after
correction. Source and report regeneration are checked separately by the root
verification and study scripts; see the current recorded acceptance result in
[`artifacts/verification/summary.json`](../artifacts/verification/summary.json).

| Finding | Correcting control | Passing regression |
|---|---|---|
| O1 | Bind every prediction to its fitted group; require complete unique group membership; reconstruct training parity bounds | `test_validator_rejects_per_contract_iv_disguised_as_heldout_fit`, `test_duplicate_and_missing_predictions_are_detected`, `test_parity_bounds_are_independently_reconstructed` |
| O2 | Recheck every frozen file before rendering | `test_report_rejects_changed_frozen_files` |
| O3 | Reconstruct row errors and every aggregate/moneyness summary | `test_validator_recalculates_errors_and_moneyness_statistics` |
| O4 | Independently declare mandatory numerical cases and CRR step inventory | `test_numerical_inventory_cannot_silently_disappear` |
| M1 | Reconstruct initial currency amounts, notionals and every HPL from reciprocal source FX without the model engine | `test_common_hundredfold_pnl_bug_is_rejected_independently`, `test_each_initial_cash_allocation_is_rebuilt_from_source`, `test_prediction_notional_is_bound_to_initial_cash` |
| M2 | Separate validation receipt binds conclusions, upstream files and validator source | `test_report_rejects_modified_assessment_and_score`, `test_report_requires_a_validation_receipt`, `test_report_detects_postvalidation_manifest_change`, `test_report_detects_changed_validator_source` |
| M3 | Check window metadata for every model row | `test_a_single_model_cannot_change_its_historical_window` |

The tests are in [market pipeline tests](../market-risk-validation/tests/test_pipeline.py)
and [option workflow tests](../option-pricing-validation/tests/test_workflow.py).
Additional root review added non-finite CRR/shock checks, complete shock inventory
and fixed-portfolio checks, and an option assessment receipt; these are covered
by `test_nonfinite_or_missing_shock_and_crr_evidence_fails` and
`test_assessment_integrity_receipt_prevents_unvalidated_report`.

These corrections strengthen validation and reporting. The market-risk forecasting
engines and statistical methods did not change: frozen prediction SHA-256 remains
`4d3b8a83534f21a2cda221d7003eb8ca73185563c2e9a3b42fa802f6142e451a`,
and the owner compared all split, stress and event statistics with the prior run
without differences. The formal synthetic audit was retained because its
statistical functions and experiment were unchanged. Option calibration parameters
and eligibility rules were not tuned to improve the low held-out spread coverage.

Both studies are historical research. Review corrections and protocol-document
consolidation after inspecting outputs are disclosed; the same evaluation sample
is not presented as a new independent prospective holdout. Passing these regression
tests closes the reproduced implementation defects, not the economic-model or
data limitations described elsewhere in the reports.
