# Market risk validation: four-minute demonstration

Six 40-second sections; pause for questions.

## 0:00 — A fixed book and a falsifiable question

Can a plausible-looking risk forecast survive independent checks? Five foreign-currency cash positions start at EUR 1m equivalent each, then remain fixed. ECB observations are reference prices; the losses are hypothetical.

## 0:40 — Only information available at the time

Historical simulation, EWMA Gaussian and EWMA filtered historical simulation share the same book. Forecasts use prior observations. FHS standardizes historical returns using their own prior volatility, preventing a subtle form of look-ahead.

## 1:20 — A proper score, not the fewest exceptions

Development selected ewma_fhs. The final comparison uses 4,097 held-out dates. Proper VaR–ES scoring penalizes underestimation and excessive buffers; exception counts alone cannot select a useful model.

## 2:00 — A profitable shock can still raise measured risk

On the CHF event date, this long-currency book gained EUR 268,605. FHS 99% VaR rose from EUR 42,704 before the event to EUR 249,471 for the next observation. The later buffer used the observed shock; it was not an advance prediction. Annual diagnostics and event replay are descriptive additions, not new significance tests.

## 2:40 — Test the validator itself

Across 200 simulated paths, the clustered-hit diagnostic rejected 100%; isolated 20% ES underestimation was detected 67% of the time. Correct-normal ES false rejection was 4.5%. These estimates have uncertainty and describe these controls, not market performance.

## 3:20 — A documented model-risk judgement

The selected model's held-out assessment is not_rejected. Gaussian forecasts had 67 99% exceptions versus 40.97 expected, and were rejected despite a lower average FZ0 score. Calibration and scoring answer different questions. Any remediation needs a new version and new evidence.
