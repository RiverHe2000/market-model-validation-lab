# Post-review diagnostics: interpretation and interview evidence

This extension was designed after the original validation was inspected. It uses
the same frozen forecasts and 2004–2025 realised cash HPL. No parameter, model,
inference method, model selection rule or original protocol was changed. It is
descriptive follow-up, not fresh out-of-sample validation.

## Complete calendar-year evidence

`validation.diagnostics.json` contains all 66 year/model cells: 22 observed years
and three models. `report/data/annual.csv` exports them. Every row retains the
actual observation count, date boundaries and original development/test assignment.
The report shows all test years, while the heatmap also includes development.

- Exception count/rate describes how often loss exceeded the previously issued
  99% VaR. Expected count is actual n × 1%. There are no annual p-values.
- Sum of excess is the sum of positive daily `(loss − VaR)` amounts. It separates
  frequency from severity; it is neither a capital requirement nor an estimate
  of losses that a different trading policy would have prevented.
- Mean VaR/ES records the amount of buffer. Mean FZ0 uses the original inception
  notional normalization. Short-period score differences are not selection rules.
- ES tail count below 20 is explicitly insufficient for the original inferential
  procedure. Reaching 20 also does not establish calibration: no annual ES tests
  are run in this extension.

On the frozen data, Gaussian has 10 exceptions in 257 observations in 2020; the
development-selected FHS has seven in each of 2011 and 2012. Its 2011 positive
VaR gaps total roughly EUR 131k, compared with roughly EUR 33k in 2012 despite the
same count. This illustrates why both frequency and severity should be visible.
These are observations from the reused sample, not new rejection tests.

## Event timing and cash attribution

The CHF anchor remains 2015-01-15. The other four anchors are the **retrospective
worst-loss dates** in the original 2008, 2015, 2020 and 2022 stress years; they must
not be described as predicted events. Each replay uses up to 20 observed dates
before and after the anchor, excluding it from pre/post means. A boundary-clipped
window is marked `truncated` and retains its actual counts. Holidays are not filled.

For each model, the evidence distinguishes:

1. Anchor-date VaR/ES, whose `anchor_as_of` precedes the realised shock.
2. The next observation's VaR, whose `next_as_of` includes the shock.
3. Pre/post risk-buffer means and subsequent exception/gap totals.

CHF-day signed portfolio HPL is approximately **+EUR 268,605**, of which about
**+EUR 218,802** comes from CHF cash. Source-quote inverses and frozen native cash
quantities independently reconstruct all five contributions. These are cash
accounting components, not causal attribution or marginal VaR decomposition.

After that gain, next-day Gaussian VaR rises about 4.97× and FHS VaR about 5.84×;
HS rises about 1.04×. A gain can increase a two-sided volatility filter and hence
a subsequent loss-tail forecast. This does not prove that either a larger or
smaller response is optimal, and the next-day buffer cannot cover the anchor
retroactively. Post-event absence of exceptions alone is not approval evidence.

## Interview walkthrough / 面试说明

- 先用全年热图解释“总体未拒绝”为什么不代表每个时期表现稳定。给出观察数量，
  说明年度结果只是诊断，没有把大量短窗检验包装成正式审批。
- 对比 2011 与 2012 的 FHS：超越次数相同，累计缺口不同，解释频率与损失幅度。
- 用 CHF 事件讲清持仓方向：冲击日是盈利，次日风险增加是模型反应，不能倒推为
  提前预测成功。再用每币种贡献验证报价倒数与冻结数量的现金会计。
- 解释为什么保留原冻结预测：本轮改善的是判断依据与可复核性，没有重新调参让
  原有测试期成绩变好。后续模型改动必须另立版本并获得新的验证证据。
- 演示 `verify` 与反例测试：修改展示文件或换用过期审计报告会被拒绝；这些是
  无签名的一致性校验，并不声称能防止整套证据被恶意重写。

## Machine interfaces

Validation schema remains 2 with an added `diagnostics_sha256`; its receipt schema
remains 1 with the same identity. The sidecar is derived from the validation file
name (`validation.json` → `validation.diagnostics.json`) and has schema 1:
`annual` is an array of year/model records; `events` contains anchor metadata,
`currency_hpl_eur`, model response records, and daily observed-date series.

`load_validation_result` verifies the sidecar hash. `load_report_receipt` additionally
binds the report's 11 generated files and current source. `load_audit_receipt`
binds synthetic JSON/Markdown and current source. All receipts are unsigned
consistency checks, not signatures or evidence of independent external approval.
