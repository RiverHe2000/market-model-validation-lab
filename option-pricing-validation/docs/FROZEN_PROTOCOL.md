# Frozen option-validation protocol v1

This protocol defines software checks and an exploratory market-model challenge. It does not establish production or regulatory model approval. “Independent” refers to separate validation code and a third-party numerical implementation, not organisational independence.

**Chronology:** these eligibility, partition, calibration and numerical rules were specified in implementation before the first full historical execution. This document was consolidated after that execution, and independent-review fixes subsequently strengthened validation and reporting. The September–December evaluation is retrospective and uses a fixed implementation protocol; it is not represented as a newly untouched prospective holdout. Audit corrections are not evidence of an additional independent test sample.

## 1. Numerical conventions and inventory

Prices are index points. Rates and volatility are annual decimals. Time is ACT/365 Fixed. Continuous dividend yield is supplied for complete-input spot cases. Negative rates are allowed. Portfolio quantities are signed and the contract multiplier is 100.

The analytic implementation uses discounted forward Black prices and put-call parity for numerical stability. Spot delta/gamma hold rate, dividend and volatility constant. Vega/rho are changes per one percentage point; theta is calendar decay per ACT/365 day. Forward delta/gamma hold the discount factor fixed and are not presented as spot Greeks.

The fixed regular analytic grid is the Cartesian product:

| Input | Values |
| --- | --- |
| Kind | call, put |
| Spot | 100 |
| Strike | 50, 80, 95, 100, 105, 120, 200 |
| Calendar days | 1, 30, 90, 365 |
| Volatility | 0.05, 0.20, 0.60 |
| Rate | −0.01, 0.05 |
| Dividend yield | 0.02 |

These 336 cases are supplemented with 12 boundaries: call/put × strikes 80/100/120 × (zero days, 20% volatility) or (90 days, zero volatility), at rate 3% and dividend 1%. Prices have deterministic limits; Greeks at the nonregular boundaries are explicitly unavailable. The independent validator checks IDs, parameters and the entire expected inventory.

CRR is a separate binomial-terminal-payoff computation, exploiting European exercise to run in O(N). It does not call the analytic price implementation. Convergence cases are the 72 combinations in the regular grid with strike 80/100/120, days 30/90/365 and volatility 0.20/0.60. Every case runs 128, 256, 512, 1024 and 2048 steps; no monotone-error claim is made. Coarse-grid risk-neutral probabilities outside [0,1] and floating-point terminal-grid overflow are explicit failures, never clipped or converted to a zero price.

Gates against the separately constructed QuantLib analytic engine:

- Analytic price absolute error ≤ `1e-9 × spot`.
- Spot Greek absolute error ≤ `1e-7 × max(1, abs(reference Greek))`, in the stated units.
- CRR at 2048 steps on the specified convergence domain: absolute error ≤ `2e-4 × spot`.
- Well-conditioned IV round trip: absolute annual volatility error ≤ `1e-5`. Impossible or limiting-boundary prices return status and no invented volatility. IV with per-unit vega below `1e-6 × discounted forward` is flagged ill-conditioned and is not included in the well-conditioned round-trip claim.
- All required prices/errors are finite, all mandatory cases and convergence steps exist, and no duplicate IDs are accepted.

## 2. Synthetic portfolio approximation experiment

The frozen portfolio has spot 100, 90 days, volatility 20%, rate 3%, dividend 1%, and four legs: +2 call K100, −1 call K110, +3 put K90, −2 put K100. Multiplier: 100.

Fifteen shocks combine spot changes −5/−1/0/+1/+5% with volatility changes −1/0/+1 percentage point and one calendar day elapsed. Approximation uses delta, half gamma times spot-change squared, vega and theta; cross and higher-order terms are omitted intentionally. An external QuantLib revaluation verifies baseline, portfolio Greeks, full-revaluation P&L, approximation and residual to an absolute tolerance of 1e-6 portfolio units (aggregate Greek tolerance 1e-7). The exact input portfolio and all 15 unique scenarios are validated. This is a model-consistent numerical example, not historical hedge effectiveness.

## 3. Quote eligibility and provenance

Input CSV columns: `underlying`, `style`, `settlement_time`, `quote_date`, `expiration`, `strike`, `type`, `bid`, `ask`, `underlying_close`; optional `quote_time`. Provider IV/Greeks are discarded. Every original row receives a source-file/row identifier. Every excluded row has an explicit reason; out-of-universe products are recorded with `unsupported_underlying` without further model processing.

Eligibility is fixed: SPXW, E, PM; quote dates 2022-07-01 through 2022-12-31; 30–180 calendar days; positive finite spot/strike; positive bid and ask; ask ≥ bid; spread/mid ≤15%; K/observed underlying close in [0.8,1.2]. Date differences approximate daily-close time to PM settlement; no intraday timestamp is inferred. Duplicate date/expiry/strike/kind rows retain the first sorted source-file occurrence and explicitly exclude later occurrences.

Rates are historical DGS3MO observations in annual decimal units. Use only the latest date **strictly before** the quote date, at most seven calendar days old. Dates absent on holidays are not filled as observations. This is a 3-month Treasury flat-rate proxy, not a maturity-matched OIS, repo, zero-rate or dividend curve. `D=exp(−rT)` is an assumption to be stressed, not an inferred market truth.

All raw file names and SHA-256s, rate hash and processed-file hashes are recorded. Hashes are integrity checks, not signatures or security controls.

## 4. Training-only calibration and exploratory failure states

The group is date/expiry. SHA-256 of `option-protocol-v1|date|expiry|strike-to-8-decimals`, first eight hex characters modulo ten, assigns buckets 0–6 to training and 7–9 to holdout. A strike's call and put remain together. July/August is development; September–December is a frozen-protocol temporal period. The latter still uses contemporaneous training strikes to calibrate each surface; it is not next-day prediction or independent quote-level sampling.

Each fitted group needs at least three training call/put pairs, training-pair strike span at least 2% of the observed spot, positive finite median forward, forward IQR/median ≤5%, and at least two holdout strikes. Every rejection retains its predeclared reason and source-group counts.

For each training pair at strike K and discount D:

`F_low = K + (call_bid − put_ask)/D`

`F_high = K + (call_ask − put_bid)/D`

The central estimate is the median training-pair midpoint forward. When all intervals have a common intersection, clip that median to the intersection and label the group `PARITY_COMPATIBLE_DAILY_PROXY`. Otherwise retain the stable median as `EXPLORATORY_INCONSISTENT_QUOTES`, record the intersection gap and fraction of pair intervals satisfied, and report its metrics separately. Interval compatibility does not establish synchrony.

Fit one volatility in [0.01,3.0] using **only training quotes**, minimizing mean squared price residual scaled by `max(half_spread,0.05)` index points. Failed optimization or a fitted boundary is rejected. Holdout values never select the forward, volatility, discount factor, quote filter or model family. The base rate, −100 bp and +100 bp assumptions each refit forward/volatility on the same training membership. Status changes under rate sensitivity remain visible.

Predict every eligible quote using the group's frozen F/D/T/sigma. Published fit metrics use holdout rows only. Base-rate holdout bid/ask IV intervals are inversion diagnostics; training and rate-sensitivity IV fields are explicitly `not_computed_training_or_rate_sensitivity`. No per-contract IV is substituted for the group's common-volatility prediction.

## 5. Evaluation and independent audit

Report coverage inside bid/ask, MAE/RMSE in index points, median absolute spread-scaled error, dates, date/expiry groups and moneyness bands: K/S ≤0.95; 0.95<K/S≤1.05; K/S>1.05. Separate temporal split, parity status and rate assumption. Observations are correlated; these counts do not justify IID confidence intervals or population-level claims. No empirical fit threshold is tuned or used to claim market acceptance.

The independent validator reads frozen files and uses QuantLib. It imports neither the pricing nor fitting module. It checks every prediction's source membership, complete date/expiry/rate inventory, constant fitted parameter binding, paired assignment, rate availability, reconstructed training parity bounds, training-only calibration objective, external prices/forward Greeks/IV endpoints, and independently recalculated published errors and summaries. It also checks all numerical cases and portfolio shocks. A generated validation receipt allows the report stage to refuse stale results, changed underlying files or a changed assessment.

Tests include deliberate counterexamples: contract-specific IV disguised as a held-out prediction, zeroed error metrics, altered parity bounds, missing/duplicate predictions, empty numerical inventory, missing CRR steps, nonfinite values, missing shock scenarios, and assessment/report tampering. Synthetic fixtures are test data only and never mixed into the historical application.

No Heston, American exercise, live surface, executable-arbitrage detection, observed trading return, production approval or financial recommendation is included.

## 6. Post-hoc descriptive extension (recorded after the original results)

This extension was chosen after inspecting the initial model study. It changes no original cleaning threshold, model, calibration, hash split or stored prediction. Its purpose is to explain existing model failures and remove a composition ambiguity in the original rate table. It is explicitly not a new predeclared hypothesis test, untouched holdout, model selection exercise or inference procedure.

**Paired rate cohort.** Join held-out predictions by their exact `quote_id`; retain the intersection present under all three discount assumptions. Observed date, expiry, kind, moneyness, midpoint and bid/ask must match across scenarios. Missing-scenario base quotes and affected group counts are reported. Each comparison uses the same common IDs. Cohort strata are fixed using **base-rate** parity status; a status change at ±100 bp is reported as an outcome. An `ALL_BASE_STATUSES` view is also provided. The original scenario-specific status rows are retained but cannot be subtracted to infer a matched effect.

Paired measures are shifted-minus-base absolute-error and spread-coverage differences, and absolute predicted-price changes. A coverage difference is expressed in percentage points. Original forward and common-volatility refits remain part of each scenario. These are full-scenario descriptive differences, not a partial derivative with other parameters held fixed and not causal interest-rate effects.

**Observation weightings.** Quote-weighted means average the paired quote contributions. Equal-date means first average the paired contributions within each date, then give dates equal weight. Equal-group means first average within each date/expiry, then give those groups equal weight. Each table reports its quote/date/group counts. These are different descriptive estimands; dates/expiries may still be dependent. No significance test, standard error, IID bootstrap or confidence interval is introduced.

**Model-failure slices.** At the unchanged base-rate quote universe, describe model-minus-midpoint bias, MAE and coverage by original split, baseline status, call/put and the original moneyness bands. Daily series and equal-date/group means complement quote-weighted results. These slices do not select, exclude or recalibrate contracts. Fixed-cohort rate summaries and base-universe error slices are separately named because their populations may differ if a rate scenario has no valid fit.

`diagnostics.json` schema v1 records input hashes, `analysis_kind=post_hoc_descriptive`, cohort counts/exclusions, `matched_rate`, `status_transitions`, `daily_base`, `daily_paired` and `error_slices`. A separate module reconstructs all tables from frozen prices using independent scalar accumulators; it imports neither the diagnostic implementation nor the model code. Regression tests cover status-switching composition, unequal quote counts per date, missing scenarios, false equal-date metrics, missing table rows and altered receipts.

**Release provenance.** The original validator receipt now binds its source files. The diagnostic receipt binds diagnostic inputs, assessment and source files. The report receipt binds results, both assessments, reporting/diagnostic source hashes and every main Markdown/HTML/figure artefact. These are reproducibility/integrity checks rather than cryptographic signatures or a security boundary. A report built against stale input, validation or source receipts is rejected.
