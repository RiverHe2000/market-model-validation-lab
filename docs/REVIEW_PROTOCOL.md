# Review and release criteria

## Before inspecting final evaluation outputs

Freeze the asset/product scope, model parameters, cleaning rules, split rules,
and inference settings described in each project's protocol. Record a hash of
the protocol, source code and data before executing the study. A correction of
an implementation defect after inspection is documented and rerun; it is not
presented as a completely untouched confirmatory experiment.

Market risk uses 1999–2003 for initialisation, 2004–2009 for development, and
2010–2025 for the final historical comparison. All daily predictors are
conditioned on previously observed data. The economic knowledge that these
years include crises is not claimed to be unknown to the researcher.

Options use July–August 2022 to develop fixed rules and September–December for
evaluation with those rules. Daily fitting to the calibration subset is allowed
by design. It must never include the held-out strike groups. Call/put pairs are
kept together. Repeated observations across dates are dependent, so quote counts
are not treated as independent sample sizes.

## Independent checks

1. Mathematical identities, dimensional checks, hand-calculated cash valuations,
   finite differences and a separately maintained reference library.
2. Deliberately invalid inputs and boundary conditions with explicit failure
   states; no silently substituted parameters or successful-looking NaNs.
3. Forecast artifact integrity: hashes, as-of dates, histories, portfolio units,
   and protocol provenance must agree before inference.
4. Tail-risk diagnostics on known simulated distributions, including false
   rejection and power limitations. A low p-value is not the sole evidence for
   a business conclusion, and a high p-value is not a certificate.
5. Quote-quality attrition, calibration/holdout isolation, rate approximation,
   settlement convention and nonsynchronous prices remain visible in reports.

## Publication boundaries

Publish the original code, offline synthetic test fixtures, aggregate results,
figures, limitations, management summaries and interview notes. Do not publish
the raw provider archive, full quote panels, implied-volatility panels that can
reconstruct the quote archive, or locally generated credentials.

The root requirements lock records the actual environment used. Windows is
tested locally. The Linux CI workflow is supplied but is not called remotely
verified unless an actual remote run is recorded. No cloud deployment or trading
integration is required by this research scope.
