---
name: unit-025-pooled-forecast
description: UNIT-025 (src/alphaledger/forecast/model.py, eligibility.py) round one, verdict conditional. The AC-2c prose-versus-implementation gap, the train/calibration overlap guard gap, and the weighted-fit-only-tested-with-uniform-weights pattern.
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
HIGH — caught myself overweighting it before the advisor call.**
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
