# Data and interpretation boundaries

The two projects deliberately distinguish mathematical verification, historical
model assessment, and what can be inferred from imperfect market observations.

## Foreign exchange

- Source: [ECB reference exchange rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).
- Currencies: USD, GBP, JPY, CHF, AUD; raw quotes are foreign currency per EUR.
- Research interval: 1999-01-01 through 2025-12-31. The immutable local snapshot,
  source metadata and hashes are recorded by the ingestion script.
- Foreign cash measured in EUR is `foreign_units / quote`. Reference rates are
  indicative observations, not executable prices. The portfolio has hypothetical
  P&L, no trading costs, financing interest or intraday trading.
- Missing observations are reported; non-trading days are not manufactured as
  zero-return days. Large actual movements are not winsorised away.
- Data downloaded today may contain revisions. A frozen historical-data study
  is not a reconstruction of every original publication vintage.

## Index options

- Source: [HistoricalData.net free samples](https://historicaldata.net/samples.html),
  an independent historical-data provider, not an exchange-operated data feed.
- The sample covers July–December 2022. The analysis is restricted to European,
  PM-settled SPXW calls and puts with 30–180 calendar days to expiry.
- The provider's 2022 `quote_time` is absent. End-of-day option quotes and
  underlying observations need not be synchronous. A parity discrepancy can
  therefore indicate stale or inconsistent data rather than an arbitrage trade.
- A short Treasury yield is used as an explicitly approximate flat discount
  input; it is not an OIS discount curve. Prior available observations avoid
  pretending to know the exact publication time of same-day data. Rate shocks
  expose the effect of this approximation.
- Forward estimates and common volatility are fitted only on calibration strike
  groups. Held-out call/put pairs do not participate in calibration. This is a
  contemporaneous cross-strike check, not a future option-price forecast.
- Supplier IVs and Greeks are not independent truth. An IV inversion followed
  by repricing the same quote is a numerical round trip, not model validation.
- Data checks can establish internal consistency and limited reconciliations;
  they cannot certify the authenticity of every vendor quote.

## Redistribution

The acquisition script saves source URLs, retrieval times, hashes, and available
license/provenance information locally. Raw and contract-level derived data are
excluded from version control. Public outputs must be aggregate analysis or
limited explanatory examples, not a reconstructed quote database. See the
[provider's terms](https://historicaldata.net/terms.html). Each reproducer obtains
the free sample directly. ECB-derived analysis is attributed to ECB and labelled
as the author's own calculations.

## Validation conclusions

A non-rejection is not proof that a model is correct. Sparse tail events and
dependent observations can make a test inconclusive. Numerical agreement among
Black–Scholes, CRR and QuantLib tests implementation under shared assumptions;
it does not establish the economic validity of constant volatility. Findings
identify evidence, impact, recommended restrictions and possible remediation.

The projects demonstrate research-level validation practice. They do not claim
bank deployment, regulatory model approval, a complete FRTB framework, actual
trading performance, or institutional second-line independence.

