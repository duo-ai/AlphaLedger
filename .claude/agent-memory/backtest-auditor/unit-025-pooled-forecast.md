---
name: unit-025-pooled-forecast
description: UNIT-025 (src/alphaledger/forecast/model.py, eligibility.py). Round one conditional (AC-2c prose gap, overlap guard gap, uniform-weight-only test pattern); round two clear, all five fixed and independently re-mutated, plus a near-miss on refusing "any supplied label" that the advisor correctly talked down.
metadata:
  type: project
---

Reviewed 2026-08-30, round one, verdict conditional.

**The generalizable lesson, worth carrying into UNIT-026's ablation review: a
weighted fit exercised only with uniform weights is untestable by
construction.** `fit` passes `uniqueness` as `sample_weight` into both the
Ridge and the LogisticRegression, an undocumented modelling choice (the intake
only justifies `uniqueness` for `effective_sample_size`, never for the fit
itself, and D-027 does not mention it either). Every success fixture in
`panel()` sets every weight to `1.0`; the one uneven-weight test
(`test_overlapping_labels_shrink_the_effective_sample_below_the_row_count`)
only checks `effective_sample_size`, not the fitted coefficients or
predictions. Deleting `sample_weight=training.weights` from both `.fit()`
calls, independently, leaves the whole suite green: with uniform weights,
weighted and unweighted least squares/logistic regression are the identical
computation, so no fixture can tell them apart. MEDIUM: the current behavior
is defensible (down-weighting overlapping labels in the fit itself, not only
in the reported sample size, is standard practice for overlapping financial
labels), but nothing pins it and nothing records the decision. Corrective test:
a minority subgroup at near-zero uniqueness following the *opposite*
relationship from the majority; assert the fitted coefficient tracks the
heavily-weighted majority's true relationship rather than an unweighted
average of both.

**AC-2c's prose promises more than the code delivers, and this is the one that
blocks.** "`fit` refuses any supplied label that the fold does not place in
its training or calibration window, naming the label" is the AC text.
`_refuse_test_features` only checks `fold.test_labels` against the supplied
`features` keys. A label the fold places in neither train, calibration, nor
test (a purged-gap label, or an arbitrary unrelated key) is never refused: `
_rows` only reads entries whose key is in `fold.train_labels` /
`fold.calibration_labels`, so the extra key is silently inert rather than
refused. Confirmed by construction: added a features/outcomes/uniqueness entry
keyed to a label outside every one of the fold's three windows and `fit`
succeeded without complaint. Harmless in effect (the extra data never reaches
the matrix), but the criterion as written is not true, which is exactly the
"prose stronger than its own falsification" pattern from
[[unit-027-forward-residual-labels]] and D-021: AC-2c's own stated falsification
test only exercises the test-window subset, so TDD against that test list could
never have caught the gap. This is the actionable, AC-bearing finding that
should resolve before merge, either by implementing the full prose (refuse any
label outside train union calibration) or by narrowing AC-2c's text to what
`_refuse_test_features` actually does.

**Train/calibration overlap is not refused, only test-window overlap is.**
`_refuse_overlapping_labels` checks `fold.test_labels` against
`fold.train_labels` and `fold.calibration_labels`, but never checks
`fold.train_labels` against `fold.calibration_labels` directly. Constructed a
hand-built `Fold` with five label ids in both `train_labels` and
`calibration_labels` (no test overlap): `fit` succeeded, and
`calibration_error` was computed partly from labels the model had also trained
on. The module's own docstring claims a general "a fold whose own label lists
overlap" guard with no test-window qualifier, which is stronger than what the
code does. Not reachable through `walk_forward` (its `_assign` places each
label in exactly one window by construction), only through a hand-built Fold,
the same threat model AC-1/AC-2 already treat as real. MEDIUM: one-line fix
(add the train/calibration intersection to the same function), squarely inside
the reviewer brief's "overlap between fit, calibration... and locked test
data" category.

**The intercept omission from `_contributions` is real but LOW/MEDIUM, not
HIGH: caught myself overweighting it before the advisor call.**
`Ridge(fit_intercept=True)` by default, and `_contributions` sums only
`coefficient * feature_value` per family, so `sum(contribution_by_family
.values()) != expected_residual_return`; the gap equals `magnitude
.intercept_` exactly (verified numerically, ~1e-4 in the fixture). Excluding
the intercept from a per-group attribution is the standard convention (linear
decomposition and SHAP both treat a constant/base value as its own term,
un-attributable to any feature group), so this is not a defect in the modeling
choice. What is actually wrong is narrower: the docstring says "Each family's
**share** of the magnitude prediction," which reads as a full decomposition,
and nothing tests whether the parts sum to the whole either way. Grading this
HIGH would have been the D-022 failure mode, a reviewer whose unbounded mandate
finds something because it must; the advisor call caught this before it went
in the report. Correction is a wording choice: name the intercept as an
explicit unattributed baseline, or reword the docstring and pin the actual
relationship with one test.

**Two independently re-verified handoff mutations, per
[[mutation-testing-discipline]]:** replacing `_effective_sample_size`'s body
with `float(len(weights))` fails `test_overlapping_labels_shrink_the
_effective_sample_below_the_row_count` (60.0 vs 41.54 expected); folding
`fold.fold_hash` into `_model_version`'s body fails
`test_two_folds_differing_only_in_their_test_window_fit_the_same_model`
(different `mdl-` hashes). Both die exactly as claimed; the handoff's six-probe
claim held up under independent replay, unlike UNIT-023's and UNIT-027's first
handoffs.

**Two low-severity coverage gaps, noted but not raised as findings:** the
`as_of` guard's `moment < self._fitted_through` is never exercised at exact
equality (`<=` survives the whole suite); `_expected_calibration_error`'s
`np.digitize(..., right=False)` versus `right=True` also survives, but
continuous logistic outputs essentially never land exactly on a bin edge so
this one barely matters.

**Out of scope, no severity, per D-022:** `TrialRegistry.register` (UNIT-024,
not this unit's file) returns an existing trial id for an identical
`(configuration, purpose, registered_at)` rather than incrementing the count,
documented there; a future reader of this unit could mistake it for a hole
here, worth a one-line pointer in a later review rather than a finding.
`test_two_processes_produce_byte_identical_forecasts` pins `PYTHONHASHSEED` but
passes an otherwise-stripped `env={"PYTHONHASHSEED": ..., "PATH": ...}` to the
subprocess, so BLAS thread count is uncontrolled; AC-7's own falsification
(observe a difference under two hash seeds) is satisfied regardless, so this
is "could not be verified" rather than a finding.

**The four implementer AC amendments, graded with the UNIT-030 discriminators:**
AC-2b (excluding `fold.fold_hash` from `model_version`) and AC-4a (splitting
out gates 5/6 via `EVALUATED_GATES`/`UNEVALUATED_GATES`) both cite a fact
established independently of this unit's own convenience (`Fold._address`'s
existing hash contents; D-006 and this unit's own path globs) and both make
the criterion strictly more falsifiable than before. Legitimate, same pattern
as [[unit-030-article-summary]]. The `uniqueness` parameter widening similarly
cites UNIT-027's own pre-existing module docstring. AC-2c is the interesting
case: the amendment itself was a reasonable thing to add during the
pre-implementation read, the problem is that the *shipped code* under-delivers
against its own text, which is a different failure from an author bending a
criterion to match what got built, worth stating precisely as such in a
report rather than folding it into the amendment-legitimacy question.

Full quality gate green: `uv sync --frozen`, `ruff check .`, `ruff format
--check .`, `mypy src` (32 files strict), `pytest` (701 passed, matches the
handoff's count exactly), `scripts/verify_harness.sh` all green.

See [[mutation-testing-discipline]] for the general probing method,
[[d022-bounded-mandate]] for how a coverage gap on correct behavior is graded,
and [[unit-030-article-summary]] for the AC-amendment discriminators applied
here.

---

Reviewed 2026-08-30, round two, verdict clear.

**All five round-one findings independently re-mutated and confirmed fixed.**
Ridge and LogisticRegression `sample_weight` deletions each independently
fail `test_the_uniqueness_weights_reach_the_fit_and_not_only_the_reported
_sample`, which is the exact pattern the round-one lesson demanded (both
estimators asserted, not only the one a lazy fixture would catch). The
train/calibration overlap guard, the intercept-exclusion pin, and the `as_of`
strict-inequality boundary each caught their own targeted mutation. AC-2c's
stranger-label refusal (Finding 1) is real: a label in neither window,
supplied only via `features`, is now refused and worded differently from a
test-window leak.

**A near-miss worth recording because I almost raised it and the advisor
correctly talked me down.** `_refuse_foreign_features` checks `features` only;
`outcomes` and `uniqueness` entries for a label outside the fold's usable set
are never refused (confirmed by construction: fit succeeds with `outcomes`
and `uniqueness` carrying entries for labels 85 through 89 against a fold
whose usable set stops at 84). The reason this is not a finding, per the
advisor: `_rows`'s own docstring makes `features` the sample-defining key in
this module's vocabulary, "a label the fold names but nothing supplied
features for is skipped." An entry in `outcomes` for a label absent from
`features` is an attribute of a label never supplied, not a supplied label
outside a window, so AC-2c's plain reading is satisfied. The plausible-refactor
argument that justified Finding 1 (`_rows` could someday iterate by
`features.keys()` instead of `label_ids`) does not transfer: `_rows` iterating
`outcomes.keys()` would try to build rows for labels with no features and fail
immediately, which is a rewrite of what a sample is, not a near-miss refactor.
General lesson for future rounds: before raising a symmetry argument
("the same reasoning that justified finding X should apply to sibling
parameter Y"), check whether the two parameters actually occupy the same role
in the function's own documented vocabulary. They frequently don't, and a
false symmetry is exactly the D-022 unbounded-mandate failure mode dressed up
as diligence.

**One real, low-severity regression from this round's own fixture churn,
found by testing the advisor's specific prediction rather than my own hunch.**
`test_supplying_features_for_a_test_label_is_refused`'s match string changed
from `"lbl-085"` to `"test window"` when the leaked-branch message was reworded
for the stranger/leaked distinction. AC-2c requires the refusal to name the
label on both branches; the stranger branch still pins this
(`match="lbl-089"` equivalent), but the leaked branch's own naming is no
longer independently pinned by any test. Confirmed by construction: replacing
`{', '.join(leaked)}` in the leaked-branch f-string with a constant "a
held-back label" (label list dropped from the message entirely) left the whole
suite green. LOW: the message still interpolates the label correctly in
production code, this is a coverage gap on correct behavior, not a functional
bug, and does not block a clear verdict. Correction: restore an assertion that
pins the specific label name in the leaked-branch message, the way the
stranger branch already does.

**Housekeeping, not a finding against the unit:** my own round-one memory
entry above contained an em dash, which failed `verify_harness.sh`'s prose
check (`.claude/rules/50-git.md` applies to this file). Fixed here; confirm
`grep -rlP '[\x{2013}\x{2014}]' --include="*.md" .` is empty before this gets
committed, since the harness cannot tell a specialist's own file from anyone
else's.

Full quality gate green: `uv sync --frozen`, `ruff check .`, `ruff format
--check .`, `mypy src` (32 files strict), `pytest` (707 passed, up from 701 by
exactly the six new round-two tests), `scripts/verify_harness.sh` all green
after the em-dash fix.
