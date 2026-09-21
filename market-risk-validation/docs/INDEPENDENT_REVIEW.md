# Independent review and artifact integrity follow-up

An independent read-only review confirmed the cash-price inversion, inception
allocations and absence of future-data influence in the forecast engines. It also
found three weaknesses in the original validation/report boundary:

1. A producer could consistently multiply every model's supplied HPL/loss by 100
   and regenerate its CSV checksum; the models agreed, but the common economic
   mistake was not independently detected.
2. A single challenger could alter its historical-window start while the first
   model's window remained correct.
3. A validation JSON conclusion or score could be edited before report generation.

The validator now reconstructs initial EUR allocations and every day's cash HPL
directly from source quotes and frozen foreign quantities, verifies every row's
history against the source calendar, and checks prediction notional against the
initial allocation. A separate unsigned validation receipt binds the exact result
bytes, run manifest, predictions and validator source before reporting. Added
counterexample tests reproduce all three original weaknesses and require rejection.

The existing prediction file was retained. Only validation and report generation
were rerun; the complete statistical split/stress/event results were compared with
the previous validation and were identical. The original validation JSON is retained
as `output/full-study/validation.pre-integrity.json` for the local evidence record.

## Synthetic audit chronology

The formal synthetic audit was completed **before** these input/report integrity
checks were strengthened. Its numerical methods, DGPs, seeds, repetitions, bootstrap
and permutation counts, Kupiec/Christoffersen computations, Z2 moment/bootstrap,
FZ0, pinball scores and Holm routine were not changed by the follow-up.

The original audit, now retained locally as
`output/validator-audit/audit.pre-optimization.json`, has its original validator-source hash:
`5db075d9f8ac75f0e93793a50ea2bf536a54fcd1e2648bd3da4359409d6db0c9`.
It is not silently relabeled as an audit of a later source file. Current validation
results and their receipt record the strengthened validator's source identity.

The audit therefore remains a recorded experiment on the unchanged statistical
routines, while the new counterexamples test the strengthened artifact boundary.
Neither the original audit nor the new integrity receipt is a cryptographic
signature or protection against malicious rewriting of an entire evidence bundle.

## Subsequent descriptive diagnostic and publishing review

The next review added exhaustive annual summaries, observed-date event response
replays and independent per-currency cash HPL attribution. These are explicitly
post-review analyses of the already-inspected data, not a revised forecast model,
new primary test family or fresh holdout. See `DIAGNOSTIC_REVIEW.md`.

The existing frozen predictions were again retained. The 5,000-draw validation was
rerun with the new diagnostic sidecar and its hash. The complete split statistics,
stress/event results, selection, seed and bootstrap settings match
`output/full-study/validation.pre-optimization.json` exactly. Numerical statistical
routines, models, parameters and frozen protocol were unchanged.

An audit receipt was added after an independent review found that a publisher
could otherwise copy a valid-looking but older synthetic audit. The **formal audit
was actually rerun** after the current audit/validation/diagnostic source files were
frozen: 200 paths of 5,000 observations, the original preset and random seeds.
Its full `results` object is identical to the previous experiment. The current
`audit.json`, `audit.md` and `audit.receipt.json` bind this new execution to current
source; the old result has not been relabeled.

The report now has a separate `receipt.json` covering the validation identity,
reporting source, Markdown, self-contained HTML, five figures and four CSV tables.
Counterexamples alter a diagnostic sidecar, an HTML file, a plotted PNG, an annual
CSV, audit evidence or generating source and require the corresponding verifier
to reject the stale or inconsistent artifact. The receipts remain unsigned.
