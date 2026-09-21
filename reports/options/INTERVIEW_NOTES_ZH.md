# 面试讲解：欧式指数期权定价验证

我把问题拆成数值实现、模型输入、模型适用性三层。独立 QuantLib 校验了 348 个冻结案例，结果 PASS；这只能证明共享假设下的实现一致性，不能证明市场模型正确。

自写 BSM 与独立 CRR，展示步数收敛、边界处理和 Greeks 单位。IV 反解后重定价不是预测成绩；真实报价只把训练 strike 拟合的同一波动率拿去检验留出 strike，call/put 成对划分。

7–8 月开发、9–12 月遵循冻结协议，但每个测试日仍用当日训练 strike 校准；这是跨行权价验证，不能说预测未来。F 只来自训练 call/put 平价；历史三个月 Treasury 是折现代理，不能叫 OIS 曲线。±100 bp 下重新拟合训练参数做敏感性。

筛选与划分规则先写在实现中，文档在完整执行后整理，审查中又修复了验证器缺口；应称回顾性固定协议评估，不声称这是从未查看过的新测试集。

有平价交集的日收盘报价仍非同步报价证明；无交集但可稳定估计的组标为探索性、不隐藏负结果。Greeks 在完整合成输入上做 spot 验证；市场 forward Greeks 不伪装真实 spot Greeks。

真实留出结果：

| Period | Parity status | Quotes | Dates | Inside bid/ask | MAE (points) | RMSE (points) |
| --- | --- | --- | --- | --- | --- | --- |
| Jul–Aug | Exploratory inconsistent | 1286 | 10 | 0.62% | 25.083 | 27.903 |
| Jul–Aug | Compatible daily proxy | 55610 | 43 | 2.54% | 16.193 | 18.807 |
| Sep–Dec | Exploratory inconsistent | 234 | 2 | 0.43% | 20.942 | 23.871 |
| Sep–Dec | Compatible daily proxy | 111319 | 84 | 2.73% | 12.92 | 15.309 |

事后补充的利率敏感性：原表按每个利率场景自己的平价状态分组，组成员会变，不能直接相减。我固定三种场景共同的报价ID，并用基准利率状态固定分层，再逐条配对计算差异；同时给每日期/到期组等权结果。它们是不同权重的描述统计，不能把相关报价当独立样本。F和sigma均重拟合，所以不是偏导rho，也不是因果效应。

| Period | Rate shift | Matched quotes | Daily mean change in MAE (points) | Daily mean coverage change (pp) |
| --- | --- | --- | --- | --- |
| Jul–Aug | -100 bp | 56896 | -0.042605 | -0.19537 |
| Sep–Dec | -100 bp | 111553 | -0.041994 | -0.08624 |
| Jul–Aug | +100 bp | 56896 | 0.043555 | 0.22658 |
| Sep–Dec | +100 bp | 111553 | 0.041453 | 0.17918 |

没有承诺 Heston、实时曲面、交易收益、真实对冲 P&L 或投产。最有价值的讨论是何时应拒绝输入、为何代码正确仍会报价不匹配、下一步需要哪些更可靠的数据。
