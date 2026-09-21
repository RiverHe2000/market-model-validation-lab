# Primary sources and reference implementations

Accessed for this implementation on 2026-09-20. Source data retrieval metadata
is recorded separately alongside each local snapshot.

## Market risk

- [ECB daily reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
  and [SDMX data API](https://data.ecb.europa.eu/help/api/data).
- [Basel MAR32: backtesting and P&L attribution](https://www.bis.org/committees/bcbs/basel-framework/standard/mar/32/inforce/2023-01-01/published/2020-03-27):
  useful context for the distinction between actual and hypothetical P&L. This
  research implementation does not implement the complete regulatory framework.
- [Acerbi and Szekely, Backtesting Expected Shortfall (2014)](https://www.msci.com/resources/research/articles/2014/Research_Insight_Backtesting_Expected_Shortfall_December_2014.pdf):
  the Z2 tail-loss moment. The local centred moving-block bootstrap is an
  explicitly approximate inference procedure, not a claim to reproduce all
  of the paper's simulation tests.
- [Patton, Ziegel and Chen (2019)](https://public.econ.duke.edu/~ap172/Patton_Ziegel_Chen_JoE_2019.pdf):
  joint VaR–ES scoring. Sign conventions are documented in the implementation.

## Options

- [Cboe SPX contract specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications):
  European exercise, cash settlement and distinctions between AM and PM products.
- [HistoricalData.net samples](https://historicaldata.net/samples.html),
  [field definitions](https://historicaldata.net/options.html) and
  [usage terms](https://historicaldata.net/terms.html).
- [Federal Reserve H.15](https://www.federalreserve.gov/releases/h15/):
  short Treasury yield reference. A flat use of this yield is a modelling proxy.
- [QuantLib European option tests](https://github.com/lballabio/QuantLib/blob/master/test-suite/europeanoption.cpp):
  third-party implementation checks; reference-library agreement is not market truth.

## Model-risk reporting

- [Federal Reserve SR 26-2, 17 April 2026](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
  replaced SR 11-7. It is background on model-risk practice, not an Australian
  compliance certification or a source of universal numeric pass thresholds.
- [Macquarie Trading Models role](https://au.linkedin.com/jobs/view/analyst-senior-analyst-model-risk-management-trading-models-at-macquarie-group-4401600232):
  a dated skills reference, not a guarantee of continuing vacancy or hiring outcome.
