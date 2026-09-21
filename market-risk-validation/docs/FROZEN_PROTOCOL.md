# Frozen protocol v1

This specification is fixed before opening the 2010–2025 model-comparison results.
Changing the models, parameter choices, portfolio, date partitions or primary
validation rules creates a new study version. A revised study must not describe
this already-inspected test period as a fresh independent holdout.

## Data and book

- ECB reference rates, 1999-01-04 through 2025-12-31; columns date, USD, GBP, JPY, CHF, AUD, quoted foreign units per EUR.
- Use observed common ECB dates only. Reject missing prices, duplicated dates/currencies, nonpositive quotes, wrong quote metadata and unsorted canonical inputs. Never forward-fill holidays or clip jumps.
- Buy EUR 1,000,000 equivalent of each foreign currency on the first available ECB date on or after 2004-01-01. Freeze foreign quantities permanently. Total inception gross notional is EUR 5,000,000.
- The construction-day closing reference quote determines quantities, so the first forecast is for the **following** observation. No construction-day backtest with a later-determined position.
- EUR asset price is 1/quote. Simple asset returns and current EUR holdings produce exact cash HPL. The book excludes interest carry, funding, execution costs and intra-day trading. This is hypothetical reference-price P&L.

## Models and chronology

- HS: 1,000 preceding five-dimensional return vectors, equal weights, full cash repricing.
- EWMA Gaussian: zero conditional mean, lambda 0.94, full 5x5 covariance, analytical normal tails.
- EWMA FHS: 1,000 preceding joint standardized vectors. Each historical return is divided by the volatility available **before that historical return**, and the whole vector is rescaled by forecast-date volatility. No independent currency shuffling.
- EWMA starts from the first 250 return outer products. Variance floor 1e-18 is solely numerical. Impossible FHS asset returns <= -100% fail the run rather than being clipped.
- Warm-up 1999–2003; development 2004–2009; held-out 2010–2025. Model selection is development FZ0 only; all held-out models and failures remain visible.
- Forecasts: one-day 97.5% VaR/ES and 99% VaR. Empirical VaR is the inverse empirical CDF; ES integrates the upper probability mass, including fractional boundary mass.

## Independent inference

- The validator independently rebuilds inception cash allocations and every day's HPL from source quotes and frozen foreign quantities, and verifies every model's historical window. It checks SHA-256 identities for data, protocol, model source, predictions and holdings. A separate validation receipt binds the resulting conclusions and scores to the run manifest, predictions and validator source before reporting. These checks detect accidental changes and inconsistent artifacts, not a malicious rewrite of an entire unsigned evidence bundle.
- Coverage: exact two-sided binomial test and Clopper-Pearson interval; Kupiec LR and its asymptotic p-value retained.
- Clustering: Christoffersen independence LR, with 5,000 conditional permutations given the observed hit count. Asymptotic chi-square inference is secondary. Fewer than two hits or non-hits is insufficient.
- ES: loss-sign Acerbi–Szekely Z2 moment, positive for underprediction. Centered circular moving-block bootstrap, block length 20, 5,000 draws, seed 42; single-sided underestimation test plus approximate 95% interval. Fewer than 20 tail observations is insufficient. This is an explicitly approximate bootstrap adaptation, not exact original-paper null simulation.
- Holm correction within each split across available model x confidence-level coverage/independence hypotheses and model ES hypotheses. No selective dropping of an unfavorable test.
- FZ0 joint score and VaR pinball losses are normalized by inception gross notional. Risk amounts and exception rates accompany scores. No ranking by fewest exceptions.
- 250-day exception windows and predeclared full calendar years 2008, 2015, 2020, 2022 are descriptive. Separately show **signed HPL** for 2015-01-14 through 2015-01-16; the worst day in 2015 is not automatically the CHF event.

## Audit and acceptance

Offline properties check price inversion, exact cash P&L, homogeneity, no future
information, preservation of joint shocks, empirical tail mass, zero-hit handling,
ES-only errors, clustering with correct overall coverage and excessive risk buffers.
The `audit` command is a separate synthetic experiment. Frozen presets and seeds are
in audit.py; `formal` estimates rejection rates over 200 paths of 5,000 observations
with 999 resamples per path. `fast` is a smoke audit, not evidence of test size.

A statistically rejected market model does not mean software acceptance failed.
Completion means reproducible forecasts, correct validation, controlled failure
tests, honest uncertainty and a reviewable decision report. Non-rejection never
becomes a claim of model correctness or regulatory approval.
