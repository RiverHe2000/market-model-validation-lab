# Data dictionary and unit conventions

The second review adds aggregate annual/event market diagnostics and paired
option scenarios. Detailed contracts are in the
[market diagnostic review](../market-risk-validation/docs/DIAGNOSTIC_REVIEW.md)
and [option diagnostic schema](../option-pricing-validation/docs/DIAGNOSTICS_SCHEMA.md).
These derived analyses are post-hoc descriptive; quote-level pairing identifiers
remain local, and only aggregate allowlisted fields enter the public explorer.

Dates use ISO `YYYY-MM-DD`; rates and volatility are annual decimals unless a
column explicitly states percentage-point scaling. Missing values retain a
documented status rather than being imputed as zeros. CSV row IDs and file hashes
are provenance keys, not economic observations.

## Canonical inputs

| File / columns | Meaning | Unit / constraint |
|---|---|---|
| `fx.csv`: `date` | Observed ECB reference-rate date | Unique, increasing; common to all five currencies |
| `USD`, `GBP`, `JPY`, `CHF`, `AUD` | Foreign currency units for EUR 1 | Positive; invert to obtain EUR per foreign currency unit |
| `rates.csv`: `date` | H.15 observation date | Observed business dates; holidays omitted |
| `rate` | DGS3MO yield divided by 100 | Annual decimal; strictly prior date selected for an option quote |
| Provider `contract` | Encoded option identifier | Checked against expiration, type and strike |
| `underlying`, `style`, `settlement_time` | Product scope | SPXW, European `E`, PM only |
| `quote_date`, `expiration` | Daily record date and expiry | 30–180 calendar days remaining |
| `type`, `strike` | Call/put and exercise price | Provider C/P normalized to call/put; index points |
| `bid`, `ask` | Daily standing quotes | Index points; both positive, ask >= bid, relative spread <= 15% |
| `underlying_close` | Daily underlying proxy | Index points; not proven synchronous with each option quote |
| `quote_time` | Provider quote timestamp | Absent in the 2022 sample; never invented |
| Provider IV / Greek fields | Vendor calculated outputs | Retained only in local source bytes; not independent reference truth |

The full 34-field source schema and archive hashes are in
[`data/manifests/options.json`](../data/manifests/options.json); vendor definitions
are linked in [SOURCES.md](SOURCES.md).

## Market-risk frozen predictions

One row per model and observed forecast date. `date` is the realization date;
`as_of` and `history_end` are the previous observed date. `history_start` is the
first return in the rolling 1,000-observation window, checked against the source
calendar. A one-day horizon here means the next reference-rate observation, which
can be separated by weekends or holidays.

| Columns | Meaning |
|---|---|
| `split`, `model` | Development/test partition and historical/ewma_gaussian/ewma_fhs |
| `pnl_eur`, `loss_eur` | Fixed-quantity cash repricing in EUR; loss = −P&L |
| `var_975_eur`, `es_975_eur`, `var_99_eur` | Upper-loss-tail risk amounts in EUR |
| `initial_gross_eur` | Frozen initial EUR 5m, used as the scoring normalization |
| `source_sha256`, `protocol_sha256`, `model_source_sha256` | Input, model specification and source-code identities |

`holdings.json` contains inception quotes and fixed foreign quantities.
`run_manifest.json` binds those holdings, predictions, source and protocol.
`validation.json` contains tests and scores; its separate receipt binds the
validated artifacts and validator source. Unsigned receipts establish consistency,
not authenticity against coordinated replacement.

## Option ingestion and predictions

| Columns | Meaning / unit |
|---|---|
| `quote_id`, `source_file`, `source_row` | Stable record lineage; row number is local provider-file provenance |
| `kind`, `strike`, `spot` | Normalized call/put; exercise price and daily underlying close in index points |
| `days`, `time` | Calendar days remaining; `time = days / 365` |
| `moneyness` | Strike / observed daily spot proxy; allowed range 0.8–1.2 |
| `mid`, `spread` | (Bid + ask) / 2 and ask − bid, index points |
| `rate`, `rate_date` | Strictly prior short Treasury yield; annual decimal and observed source date |
| `split` | development for July–August; temporal_test for September–December |
| `assignment` | train or holdout; paired call/put strike groups assigned together |
| `quality_flags` | Explicit limitations including absent quote time |
| `rate_shift` | −0.01, 0, +0.01 annual-rate perturbation; fit is repeated on training strikes |
| `discount`, `forward` | exp(−shifted rate × time); training-parity-implied forward in index points |
| `sigma` | One fitted annual volatility per date/expiry/rate-shift group |
| `group_status` | Parity-compatible daily proxy or exploratory inconsistent daily quotes; rejected groups live in groups.json |
| `model_price` | Forward Black price in index points, bound to the fitted group's parameters |
| `error`, `absolute_error` | Model price − quote midpoint, and its absolute value |
| `within_spread` | Indicator that bid <= model price <= ask |
| `spread_scaled_error` | Signed pricing error / max(half bid–ask spread, 0.05 index points); the floor is declared for numerical stability |
| `iv_bid`, `iv_ask` | Diagnostic quote-implied annual volatility endpoints when identifiable |
| `iv_bid_status`, `iv_ask_status` | Explicit solver/boundary/not-computed states; only base-rate holdout records receive the interval diagnostic |
| `forward_delta`, `forward_gamma` | Derivatives with respect to forward with discount fixed; not spot hedging Greeks |
| `vega_1pct` | Price change per +1 percentage point annual volatility |

Synthetic numerical benchmarks use spot Greeks. Their theta is per calendar day,
rho and vega per one percentage point, and gamma per squared spot unit. Expiry and
zero-volatility kinks carry explicit nonregular-boundary states. The synthetic
four-leg shock portfolio multiplies contract values by 100; these are model
experiments, not historical realized P&L.

`ingest_exclusions.csv` retains each excluded row's reason. `groups.json` binds
calibration and holdout members and fitted parameters. `results.json` binds frozen
files and retains aggregate study and numerical results. `validation.json`
records external QuantLib checks, reconstructed statistics and failure states.
Only aggregate reports are suitable for public redistribution.
