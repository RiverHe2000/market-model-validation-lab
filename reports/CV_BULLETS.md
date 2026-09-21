# Evidence-based CV bullets and interview pointers

These claims describe the completed local study, not production deployment or trading performance. Adapt the wording to the role; retain the qualifications.

## Market risk validation

- Built a reproducible EUR FX cash-book validation study using 6,913 ECB observations; compared historical, EWMA Gaussian and filtered historical VaR/ES over 4,097 held-out dates.
- Implemented independent coverage, clustering and approximate ES diagnostics, proper VaR–ES scoring, stress analysis and a 200-path synthetic audit with uncertainty intervals; retained rejected models and data limitations.

## European index option pricing validation

- Implemented analytic European option prices, Greeks, IV inversion and independent CRR convergence checks; validated 348 frozen benchmark cases against QuantLib.
- Screened 4,294,301 vendor sample records to 558,506 eligible SPXW quotes, calibrated common volatility on training strike groups and evaluated withheld strikes with explicit quote-synchronization and discount-proxy limitations.

## 中文面试回答顺序

先讲金融问题和单位约定，再展示一项可复核结果，最后解释影响与适用限制。市场风险应解释评分与覆盖率为何可能给出不同信息；期权应解释实现正确为何不等于市场拟合充分。用验证器反例说明你怎样发现错误，不把测试数量当作经济模型有效性的证明。
