# Index option pricing validation: four-minute demonstration

Six 40-second sections; pause for questions.

## 0:00 — Two different questions

Does the pricing implementation calculate the assumed model correctly? Does that model explain observed quotes? Agreement with QuantLib answers the first question, not the second.

## 0:40 — Analytic, numerical and reference checks

The frozen benchmark contains 348 checked cases. Analytic prices and Greeks are compared with QuantLib, and independent CRR grids measure convergence. Boundary and invalid cases retain explicit states.

## 1:20 — A free, imperfect market sample

The source has 4,294,301 rows; 558,506 meet the fixed product and data rules. Only European PM-settled SPXW options, 30–180 days, enter the study. Quote times are missing, so synchronization is not established.

## 2:00 — Fit once, test different strikes

Whole call/put strike groups are assigned to calibration or holdout. Training pairs determine the forward; one common volatility is fitted per date and expiry. Every prediction must remain bound to those fitted parameters. Replacing each holdout volatility by its inverted quote IV is explicitly rejected.

## 2:40 — Model misspecification and input uncertainty

Among 111,319 September–December held-out quotes in parity-compatible daily groups, common-volatility spread coverage is 2.73% and mean absolute error is 12.92 index points. Poor fit remains visible. Missing timestamps and the flat Treasury proxy prevent clean attribution of all error to the model. Per-contract IV is diagnostic, never held-out accuracy.

## 3:20 — Compare the same quotes before attributing the error

On 111,553 fixed September–December held-out quotes across all base statuses, a ±100 bp discount scenario changes MAE by at most 0.042 points after training-only recalibration; baseline MAE is 12.94. Changing cohort composition can exaggerate apparent sensitivity. This is descriptive scenario evidence, not causal identification or proof that data uncertainty is immaterial.
