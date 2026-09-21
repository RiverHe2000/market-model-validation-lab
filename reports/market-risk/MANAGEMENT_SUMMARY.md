# Market risk: management summary

The development-selected method is **ewma_fhs**. On **4,097 held-out observations**, its assessment is **not_rejected** after multiplicity adjustment. This is a research finding, not production approval.

| Model | Held-out days | 99% exceptions | Mean FZ0 | Assessment |
|---|---:|---:|---:|---|
| ewma_fhs | 4,097 | 47 | -4.7012 | not_rejected |
| ewma_gaussian | 4,097 | 67 | -4.7257 | rejected |
| historical | 4,097 | 47 | -4.6096 | not_rejected |

The EUR 5m-initial cash book holds fixed quantities of five currencies. Quotes come from ECB and losses are hypothetical. Reference-rate observations omit transaction costs, funding and liquidity effects.

Decision: review coverage, tail-loss magnitude and exception clustering together. An unlimited risk buffer is not a model improvement. A non-rejected test is not proof; sparse tails and regime changes limit inference. Any remediation should be documented as a new model version and evaluated on genuinely new evidence.

The independent validator reads frozen forecasts, applies coverage/independence tests and a separate ES diagnostic, and retains proper scoring, uncertainty and stress periods. See the full report for hypotheses, provenance and limitations.
