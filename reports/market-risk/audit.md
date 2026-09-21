# Synthetic audit of the validation methods

Preset: **formal**. These are synthetic controls, not market performance.

Protocol: {'repetitions': 200, 'observations': 5000, 'bootstrap_samples': 999, 'permutations': 999, 'block_length': 20, 'seed': 20260920}

| Scenario | Coverage rejection rate | Independence rejection rate | ES-underestimation rejection rate | Mean FZ0 difference vs correct forecast |
|---|---:|---:|---:|---:|
| normal_correct | 0.045 | 0.040 | 0.045 | 0.0000 |
| student_t5_correct | 0.060 | 0.020 | 0.040 | 0.0000 |
| student_t5_as_gaussian | 0.110 | 0.025 | 0.575 | 0.0127 |
| clustered_hits | 0.245 | 1.000 | 0.010 | 0.0000 |
| es_only_20pct_low | 0.060 | 0.020 | 0.670 | 0.0265 |
| risk_buffer_5x | 1.000 | 0.000 | insufficient | 1.4472 |

- Each test is assessed at nominal 5% before Holm; these repetitions estimate size/power, not individual model approvals.
- Correct-distribution rejection frequencies have binomial uncertainty; do not require every null sample to pass.
- The clustered scenario preserves normal marginal tails while violating temporal independence.
- ES-only distortion retains the correct Student-t VaR and lowers ES while preserving ES >= VaR.
- The 5x buffer is judged on coverage and FZ0, not rewarded for suppressing exceptions.
- Fast preset is a smoke audit with wide intervals; formal preset is the predeclared statistical experiment.
- Bootstrap inference remains approximate; any material size distortion is a limitation to report, not tune away on market holdout.

The JSON includes exact binomial 95% intervals and denominators for every rejection frequency.
