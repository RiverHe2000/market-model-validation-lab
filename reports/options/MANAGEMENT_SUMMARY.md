# Management summary

Software validation: **PASS**, based on 348 frozen cases and an external QuantLib implementation. There are 0 unresolved automated findings.

Market model acceptance is **not established**. The limited SPXW daily quote study evaluates one volatility per date/expiry on held-out strikes; it does not demonstrate a live pricing service or future trading performance.

This is a retrospective fixed-protocol experiment. The protocol was consolidated into documentation and audit defects were corrected after the first complete execution; no fresh prospective holdout is claimed.

| Period | Parity status | Quotes | Dates | Inside bid/ask | MAE (points) | RMSE (points) |
| --- | --- | --- | --- | --- | --- | --- |
| Jul–Aug | Exploratory inconsistent | 1286 | 10 | 0.62% | 25.083 | 27.903 |
| Jul–Aug | Compatible daily proxy | 55610 | 43 | 2.54% | 16.193 | 18.807 |
| Sep–Dec | Exploratory inconsistent | 234 | 2 | 0.43% | 20.942 | 23.871 |
| Sep–Dec | Compatible daily proxy | 111319 | 84 | 2.73% | 12.92 | 15.309 |

## Post-hoc fixed-cohort sensitivity

| Period | Rate shift | Matched quotes | Daily mean change in MAE (points) | Daily mean coverage change (pp) |
| --- | --- | --- | --- | --- |
| Jul–Aug | -100 bp | 56896 | -0.042605 | -0.19537 |
| Sep–Dec | -100 bp | 111553 | -0.041994 | -0.08624 |
| Jul–Aug | +100 bp | 56896 | 0.043555 | 0.22658 |
| Sep–Dec | +100 bp | 111553 | 0.041453 | 0.17918 |

These paired differences hold quote membership and baseline strata fixed. They include training-parameter refits; they are descriptive, not causal rho. Original scenario-specific parity tables have changing composition and cannot supply this comparison.

Decision: use the package as a reproducible model-validation research case. Separate implementation correctness, discretisation error, input uncertainty and constant-volatility model risk. Timestamp uncertainty, Treasury discount proxies and inconsistent parity intervals prevent a claim of validated market calibration.
