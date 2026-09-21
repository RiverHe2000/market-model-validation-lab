# Second review: diagnostics, presentation and reproducibility

This revision adds explanatory evidence to the completed historical studies.
Models, eligibility rules, calibration splits and primary forecasts are unchanged.
The new annual, event and matched-scenario results are **post-hoc descriptive
analyses**, not a newly untouched evaluation sample or new significance tests.

## Market risk: locate the failure and respect information timing

The report now includes 66 year/model cells covering 2004–2025, with exception
rates, tail counts, mean risk estimates, proper scores and excess-loss magnitude.
Sparse annual tails remain visible rather than being turned into annual approval
decisions. Four retrospective worst-loss days in the predefined stress years
and the fixed CHF event date have explicit before/after information boundaries.

The five-currency long cash book **gained EUR 268,605** on 15 January 2015.
FHS 99% VaR was approximately EUR 42,704 before that event and EUR 249,471 for
the next observation. A profitable shock can increase measured risk. The latter
forecast had already observed the shock and cannot demonstrate advance warning.
Currency attribution reconciles to book HPL, and pre/post comparisons use observed
dates rather than fabricated holiday returns.

The independent validator checks the diagnostic inventory, input provenance and
source identity. The formal 200-path audit was rerun in this revision after
strengthening its integrity receipt; its rejection-rate results were unchanged.
See the [diagnostic review](../market-risk-validation/docs/DIAGNOSTIC_REVIEW.md).

## Options: compare the same contracts and disclose the averaging rule

The three discount scenarios now use a common set of quote identifiers, fixing
each group's stratum at its baseline status. Scenario-dependent changes in parity
compatibility are outcomes, not silent changes in which quotes enter the comparison.
The full common population is 168,449 quotes across 1,603 date/expiry groups and
127 dates; this dataset loses no baseline holdout quotes at the intersection.

In September–December, the **all-baseline-status** common set has 111,553 quotes,
1,106 date/expiry groups and 84 dates. Quote-weighted baseline MAE is 12.93674
index points. After training-only recalibration, −100 bp changes MAE by −0.04224
points and +100 bp by +0.04162 points. This is a complete recalibration scenario,
not a pure Rho sensitivity or causal estimate of a market rate move. The original
111,319-quote parity-compatible subset and its 2.73179% coverage remain a separate
reported population.

The report and explorer also provide equal-date and equal-date/expiry weights,
daily dispersion, and call/put error slices by strike/spot ratio. Equal weighting
does not make repeated observations independent. The signed errors are consistent
with a missing skew effect, but nonsynchronous quotes and approximate discount
inputs prevent attributing all error to a single model assumption. No new
confidence intervals or significance claims are attached to these diagnostics.
See the [diagnostic data contract](../option-pricing-validation/docs/DIAGNOSTICS_SCHEMA.md).

## Presentation and execution

- The [interactive evidence page](../reports/evidence.html) switches years,
  models, events, baseline strata, averaging rules and option types. It consumes
  aggregate allowlisted data; quote identifiers and exclusion panels stay local.
- The landing page leads with the two actual findings. Both four-minute tours,
  management summaries, full reports and interview notes remain available.
- `run_study.py --from-stage validate` revalidates frozen outputs and regenerates
  diagnostics/reports. Per-step state is recorded before launch and child output
  is written continuously to a local execution log. Interruption retains an
  `INTERRUPTED` receipt; it does not leave a completed `PASS`.
- A new verification starts by invalidating the previous status. Passing evidence
  is bound to the complete relevant source/test/config inventory and dependency
  versions, so later additions, removals and edits invalidate it.
- The gallery checks both projects' report receipts and the audit receipt. It is
  built and link-checked in a private staging directory before replacement. Failed
  builds preserve the last complete gallery; failed final replacement restores it.
  The prior gallery is retained in local publication history.

Receipts are consistency checks, not signatures or protection from a person who
can rewrite every file. A successful software check does not approve an economic
model. Original Gaussian coverage rejection and poor constant-volatility market
fit remain visible.

## Acceptance

Final local test counts, browser checks and unchanged primary-output fingerprints
are recorded in [ACCEPTANCE.md](ACCEPTANCE.md). Remote CI is configured but has not
been claimed as executed.
