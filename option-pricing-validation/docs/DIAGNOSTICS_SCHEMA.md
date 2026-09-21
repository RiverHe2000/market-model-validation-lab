# Post-hoc diagnostic artefact contract

`output/full-study/diagnostics.json` has `schema_version: 1`, `analysis_kind: post_hoc_descriptive` and `recipe: fixed-cohort-rate-and-error-diagnostics-v1`. It does not replace or alter `results.json` or historical predictions. No test of statistical significance is performed.

| Field | Contents |
| --- | --- |
| `input_hashes` | SHA-256 of results, predictions, groups, validation and validation receipt |
| `population` | Base held-out and all-three-scenario common quote/group/date counts, exclusions and scope |
| `pair_exclusions` | Base quote ID, date, expiry, and missing rate scenarios |
| `matched_rate` | One row per split × fixed base parity status × nonzero rate shift, including `ALL_BASE_STATUSES` |
| `status_transitions` | Base and shifted parity states, rate shift, split, quote/date/group counts |
| `daily_paired` | Date × split × base status × rate shift; within-date paired descriptive measures |
| `daily_base` | Date × split × base status; original base universe's MAE, signed error and coverage |
| `error_slices` | Split × base status × call/put/all × original moneyness band/all; three descriptive weightings |

For the principal matched-rate view, select `base_group_status == ALL_BASE_STATUSES`. `split` is `development` (July–August) or `temporal_test` (September–December). `rate_shift` is annual decimal −0.01 or +0.01. The same quote IDs are used in both rate rows and the matching base values. The original forward and common volatility are refitted at each rate, so this is a full recalibration comparison, not partial rho or a causal rate effect.

`matched_rate` carries `common_quotes`, `common_groups`, `dates` and these measures:

- `base_mae_points`, `shift_mae_points`, `delta_mae_points`;
- `base_coverage`, `shift_coverage`, `delta_coverage_pp`;
- `mean_abs_price_change_points`.

Each measure also has `equal_date_` and `equal_group_` variants. Unprefixed means are quote weighted. Equal-date means first average within date then across dates. Equal-group means first average within `(quote_date, expiration)` then across those groups. A group's membership can differ by diagnostic slice. Equal weighting changes the estimand; it does not establish independence.

Prices, MAE and signed errors are in index points. Coverage fields are fractions in JSON; multiply by 100 for display. Fields ending `_pp` are already percentage points and must not be multiplied by 100. The report renders fractions as percentages. `error_slices` includes `quotes`, `dates`, `groups`, `mae_points`, `mean_error_points`, `coverage` and the two weighting prefixes. Positive signed error means model price exceeds the observed midpoint. Moneyness uses observed daily spot, not forward delta.

The independent reconstruction reads frozen prices and audits every table with separate scalar accumulators. `diagnostics_validation.json` contains `status`, `failures`, `diagnostics_sha256`, `input_hashes`, `common_quotes` and `audited_tables`. Its receipt binds both analysis source files and the payload/assessment hashes. The original validation receipt separately binds the original validator source files.

`report_receipt.json` binds validation, validation receipt, results, diagnostics, diagnostic assessment, diagnostic receipt, the three reporting/diagnostic source files and every main Markdown/HTML/chart file. The public `load_report_receipt(output: Path)` checks all these relationships, the original validator sources, frozen result files and the exact set of HTML-referenced figures. It raises on stale or incomplete evidence. Receipts are consistency records, not signed security guarantees.

When software validation fails, `report` still writes a failure report with `diagnostics_status: NOT_PERFORMED_SOFTWARE_FAILURE`, no diagnostic claims and no figures. Diagnostics hashes are then absent, rather than borrowing a previous successful assessment. A valid receipt can describe a failed study; a publisher must separately decide whether its validation status is acceptable.
