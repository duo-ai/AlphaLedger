---
id: UNIT-025
title: Fit the pooled forecast and emit the Forecast record
lane: research
state: in_review
owner: mazwy/claude
branch: feature/025-pooled-forecast
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-022, UNIT-023, UNIT-024, UNIT-027]
paths: src/alphaledger/forecast/model.py, src/alphaledger/forecast/eligibility.py, tests/research/test_model.py, tests/research/test_eligibility.py, pyproject.toml, uv.lock, project-state/DECISIONS.md
claimed_at: 2026-08-30T11:49:32Z
---

## Problem

Four research units are merged and none of them answers anything. UNIT-022
builds the price family, UNIT-023 builds the news family, UNIT-024 cuts
chronological purged folds and refuses an unregistered trial, and nothing
consumes a fold. The trial registry has been proven to reject what it should
and has never been exercised against a real research run, so the discipline is
real and untested at the same time. Until something fits a model on a training
window, calibrates on the next one, and emits a `Forecast`, the lane has built
two feature families and produced no evidence that either predicts anything.

`Forecast` is already frozen in design section 14 with eleven fields, including
`eligible`, `rejection_reasons`, `contribution_by_family`, and
`calibration_error`. Nothing produces one. Every downstream unit, the structure
enumeration in UNIT-014 above all, consumes a record that no code emits.

## Source of truth

- `options-alpha-agent-design.md` section 6, both the model subsection and the
  trade eligibility subsection.
- `options-alpha-agent-design.md` section 7 for the validation protocol.
- `options-alpha-agent-design.md` section 14 for the frozen `Forecast` record.
- `.claude/rules/20-research-integrity.md`.
- `src/alphaledger/forecast/splits.py`, `Fold`, `Window`, `Labelled`, and
  `SplitConfig`, merged by UNIT-024.
- `src/alphaledger/forecast/registry.py`, `TrialRegistry.register` and
  `record_result`, merged by UNIT-024.

## Scope

In:

- a pooled estimator fitted on a fold's training window and calibrated on its
  calibration window, never on its test window;
- the probability-of-positive-residual model and the residual-magnitude model
  design section 6 names;
- calibration measurement producing the `calibration_error` the record holds;
- `contribution_by_family` computed so the price and news families can be
  attributed separately, which is what makes UNIT-026's ablation meaningful;
- the deterministic eligibility gate from section 6, emitting `eligible` and
  the `rejection_reasons` an ineligible forecast is required to carry;
- registration of every fit as a trial before its result is examined.

Out:

- the baselines and ablations that compare the families (UNIT-026). This unit
  fits one model and must not also be the thing that judges it.
- ranking and portfolio diversification, section 6's third subsection. It
  operates across candidates and belongs with whatever assembles a scan.
- threshold selection on development data. This unit takes thresholds as frozen
  configuration and does not choose them; choosing them is a registered trial
  and a separate act.
- the label construction that produces forward residual returns (UNIT-027).
  Writing this intake surfaced that no row owned it, and the resolution was to
  give it one rather than absorb it here. A label is point-in-time evidence,
  not modelling, and UNIT-026 compares models against exactly these labels, so
  a label built inside one of the things being discriminated between could not
  be trusted by the other. `outcomes` therefore arrives as an input to `fit`
  and this unit never derives it.

## Contract

`alphaledger.forecast.model.fit(fold, features, outcomes, uniqueness, config,
registry, registered_at) -> FittedModel`, where `fold` is UNIT-024's `Fold`,
`features` maps a `label_id` to the merged price and news feature mapping for
that instant, `outcomes` maps a `label_id` to its realised forward residual
return, and `uniqueness` maps a `label_id` to the uniqueness weight UNIT-027's
`with_uniqueness` computed for it.

`uniqueness` was added to this contract on 2026-08-30, by the
pre-implementation read, and it is required rather than optional. Without it
`effective_sample_size` could only be the training row count, and the row count
is precisely the lie UNIT-027 computes uniqueness to prevent: sampling daily at
a multi-session horizon makes consecutive labels share most of their outcome
window, so a fit counting rows counts the same information many times. Gate 4
in `eligibility.py` refuses a candidate whose effective sample size is too
small, and a gate fed the row count would refuse almost nothing. UNIT-027's own
module docstring already states that this unit is expected to carry uniqueness
into the fit; the contract had simply omitted the channel. Defaulting it to one
per label was rejected for the same reason a missing quantile band is not
treated as a narrow one: it is the most flattering reading of absent data. Fitting registers a trial through `TrialRegistry.register` before any
result is computed, and returns a model carrying `model_version`, the fold
hash, and the trial id.

`FittedModel.predict(candidate_id, features, as_of) -> Forecast` emits the
frozen record from design section 14. `p_up`, `expected_residual_return`,
`quantiles`, `contribution_by_family`, `calibration_error`, and
`effective_sample_size` are all populated; none is defaulted.

`alphaledger.forecast.eligibility.decide(forecast, families, config) ->
Forecast` returns the record with `eligible` and `rejection_reasons` set. It is
a pure function of the forecast, the families that contributed, and frozen
configuration.

Errors: `LeakedFitError` when a training or calibration input carries an
instant the fold does not admit; `UncalibratedModelError` when `predict` is
called before calibration; `UnregisteredTrialError` propagates unchanged from
UNIT-024 rather than being caught.

## Assumptions

Eligibility thresholds arrive as a frozen dataclass parameter rather than from
`config/`. This unit's path globs cover `src/alphaledger/forecast/**` and its
tests, so it cannot add `config/model.toml`, and no such file exists today.
D-017 wants a threshold that explains a decision to be committed and hashed, so
this is a gap rather than a design, and it is the same gap UNIT-013 and
UNIT-017 already record: both take thresholds as required explicit parameters
because `config/risk.toml` does not carry them. Recorded here so the later
change that commits these values has one place to look. Every default declared
here is declared, not selected on data, per design section 4.

The estimator is ridge and logistic regression from scikit-learn, already in
the dependency set, rather than anything hand rolled. `AGENTS.md` requires
naming the package that already solves the problem, and a bespoke solver would
have to earn its own correctness tests before it could be trusted with a claim.

Symbol identity is not a feature, per section 6. Sector and volatility regime
are admitted as coarse controls only.

The two models share one feature matrix and one fit call each. Section 6 asks
for a deliberately simple pooled model, so no per-sector or per-regime model is
fitted.

`quantiles` are produced from the residual distribution of the calibration
window rather than from a quantile regression, because a second estimator would
be a second set of unselected hyperparameters.

## Acceptance criteria

- AC-1: a fit whose training input contains an instant outside the fold's
  training window raises rather than silently fitting on it. Falsified by
  constructing a fold, passing one label from its test window, and observing
  that the fit succeeds.
- AC-2: nothing from the test window reaches the fit or the calibration.
  `Fold` carries `test_labels`, so `fit` is handed them and must ignore them.
  Falsified by building two folds identical in every respect except the
  contents of their test windows, fitting both, and observing that
  `model_version` or any emitted `Forecast` value differs. A fit that reads
  test labels cannot pass that; one that ignores them cannot fail it.

  This criterion was rewritten on 2026-08-29, before the unit was ever
  claimable, because the first version was unfalsifiable. It said to mutate a
  test-window outcome after fitting and observe whether a forecast changed,
  which cannot happen either way once the model object is built, so the
  observation was true unconditionally. It also contradicted AC-1: a fit
  containing an out-of-window instant raises, so the leaking fit the mutation
  was supposed to expose could never be constructed. D-021 records this exact
  failure against UNIT-010, where a criterion that read as considered was
  unsatisfiable in principle and the test list faithfully reproduced its false
  premise.
- AC-2b: `model_version` is derived from the training-relevant view of the
  fold only, never from `Fold.fold_hash`. Falsified by two folds differing only
  in their test label lists producing different `model_version` values.

  Found by the pre-implementation read, and it is what makes AC-2 satisfiable
  at all. `Fold._address` in the merged `splits.py` hashes `test_labels` into
  `fold_hash`, so two folds identical but for their test windows already have
  different fold hashes. A `model_version` folding in `fold_hash` would
  therefore differ, and AC-2 could never pass however carefully the fit ignored
  the test window. The model still carries `fold_hash` as provenance, which is
  what the contract asks for; it simply is not an input to the model's own
  identity. Provenance and identity are different questions and this is the one
  place they visibly diverge.
- AC-2c: `fit` refuses any supplied label that the fold does not place in its
  training or calibration window, naming the label. Falsified by supplying a
  label from `fold.test_labels` and observing a fit. Reading `test_labels` in
  order to refuse is not reading them in order to fit, and does not affect
  AC-2: with valid input no test label is present, so its contents cannot move
  a fitted parameter.
- AC-3: every fit registers a trial before its result is computed, and the
  registered configuration includes the feature versions of both families and
  the fold hash. Falsified by fitting and observing the registry count is
  unchanged, or observing a registered configuration that omits either
  `feature_version`.
- AC-4: an ineligible forecast carries at least one rejection reason, and each
  reason names the specific gate from section 6 that refused it. Falsified by
  producing an ineligible forecast whose reason does not correspond to a
  numbered gate. The empty case is already refused by the frozen record.
- AC-4a: `decide` evaluates gates 1 to 4 only, and the module states which
  gates it does not evaluate through exported constants, so a caller cannot
  mistake four gates for six. `eligible` therefore means "cleared every gate
  this function evaluates" and never "cleared section 6". Falsified by
  `EVALUATED_GATES` or `UNEVALUATED_GATES` being absent from the module, by
  their union not being gates 1 to 6, or by a rejection reason naming a gate
  outside `EVALUATED_GATES`.

  The frozen `Forecast` record cannot carry this, and widening it is out of
  scope: it is UNIT-001's file and this unit's globs do not reach it. Exported
  constants are the honest alternative, because they are checkable by a test
  rather than only stated in prose.

  Recorded on 2026-08-30, from the pre-implementation read D-026 requires, and
  before any code was written. Section 6 lists six conditions, and two of them
  are not computable from this function's declared inputs. `decide` is a pure
  function of one forecast, its contributing families, and frozen
  configuration, and:

  - Gate 5, that the signal is not concentrated in one symbol, one week, or one
    sector in the held-out evaluation, is a property of the evaluation across
    all candidates, not of any single forecast. One forecast cannot see the
    distribution it belongs to. This belongs to UNIT-026, which owns the
    baselines and ablations over the held-out set.
  - Gate 6, that current data, chain, account, and portfolio checks pass, is
    execution-lane state. This unit's declared path globs are `forecast/**`
    only, so it cannot reach that code, and D-006 keeps account facts out of
    the coding agent's reach entirely. This belongs to the pre-trade check on
    the execution side.

  Narrowing the function is therefore correct and widening it is not: a
  `decide` that claimed to clear gates 5 and 6 would be asserting something it
  has no input for, which is worse than one that reports what it checked. What
  the unit must not do is let a caller mistake four gates for six, so the
  emitted record names the gates that were evaluated.

  Section 6's own wording supports this: it lists conditions under which "a
  candidate reaches structure construction", which is the whole pipeline, not
  one function. The test list's "clears all six gates" line is corrected below
  for the same reason.
- AC-5: a candidate where only one family contributes is ineligible, per
  section 6 gate 1, and says so. Falsified by supplying a news-only candidate
  and observing `eligible` is true.
- AC-6: a candidate whose families disagree on direction is ineligible and says
  so, distinctly from the single-family case. Falsified by observing one shared
  reason for both.
- AC-7: refitting the same fold with the same features, outcomes, and
  configuration in a separate process produces the same `model_version` and the
  same `Forecast` values. Falsified by any difference under two
  `PYTHONHASHSEED` values, which is how UNIT-022 and UNIT-023 check the same
  property.
- AC-8: `contribution_by_family` attributes to `price_volume` and `news`
  separately, and the two attributions are computable independently of each
  other. Falsified by an attribution that changes when a family the candidate
  does not use is added to the configuration.
- AC-9: a fold whose calibration window holds no usable label raises from
  `fit` rather than returning a model, because `predict` returns a `Forecast`
  and has no way to return nothing, and a record carrying an invented
  `calibration_error` is worse than no record. `EMPTY_CALIBRATION_WINDOW`
  already exists in UNIT-024's `splits.py`, so the fold is constructible.
  Falsified by observing `fit` return a model from such a fold.

## Test list

- success: a hand-built fixture with a known linear relationship recovers a
  `p_up` above one half for the positive case and below it for the negative,
  and the sign of `expected_residual_return` matches.
- success: `contribution_by_family` names both families and both are non-zero
  when both contribute.
- success: an eligible candidate clears gates 1 to 4 from section 6 and carries
  no rejection reason, while `UNEVALUATED_GATES` names the two it did not check
  so four cannot be mistaken for six (AC-4a). This line read "all six gates" before the
  pre-implementation read found that gates 5 and 6 are not computable from
  `decide`'s inputs.
- failure: a training input from the test window raises `LeakedFitError` naming
  the label and the window. This is the deliberately leaked fixture the
  research rules require.
- failure: a calibration input from the test window raises, separately from the
  training case, so the two leaks are distinguishable.
- failure: two folds differing only in the contents of their test windows
  produce the same `model_version` and the same forecasts, which is the
  observation AC-2 names. A fit that read `Fold.test_labels` would fail it.
- failure: `predict` before calibration raises `UncalibratedModelError` rather
  than returning an uncalibrated probability.
- failure: fitting against a registry that refuses the registration propagates
  the error rather than fitting anyway.
- failure: a candidate with one contributing family is ineligible, and its
  reason differs from the reason a disagreeing pair gets.
- failure: a probability below the frozen floor is ineligible even when every
  other gate passes, because section 6 calls that floor non-negotiable.
- restart: refitting the same fold in a separate process reproduces
  `model_version` and every emitted `Forecast` field, under two hash seeds.
- restart: a model persisted and reloaded emits identical forecasts, so a
  frozen run can be replayed.
- no-trade: a fold whose calibration window holds no usable label raises from
  `fit`, naming the fold and the window, rather than returning a model whose
  `calibration_error` no data supports.
- no-trade: a candidate missing the news family entirely does not silently
  downgrade to a price-only eligible trade, per section 6, and is recorded as
  shadow rather than eligible.

## Verification

```bash
uv run pytest tests/research/test_model.py tests/research/test_eligibility.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

## Handoff notes

Two modules. `eligibility.py` evaluates the section 6 gates that a single
forecast can decide; `model.py` fits the pooled ridge and logistic pair and
emits the frozen `Forecast`.

### What the pre-implementation read changed, before any code existed

Four contract defects were found by reading this intake against the merged code
first, as D-026 requires. All four are recorded in the acceptance criteria
above with their reasoning; they are collected here because together they are
the argument for doing that read at all.

Gates 5 and 6 are not computable from `decide`'s inputs, so AC-4a splits them
out and the module exports `EVALUATED_GATES` and `UNEVALUATED_GATES` rather
than letting `eligible` read as "cleared section 6".

`Fold.fold_hash` hashes `test_labels`, so a `model_version` derived from it
would have made AC-2 unsatisfiable: two folds differing only in what they hold
back already carry different fold hashes. AC-2b now states that
`model_version` excludes it, and the model carries the fold hash as provenance
instead. This one would have cost a review round and looked like a bug in the
fit rather than a contradiction in the specification.

`fit` had no channel for label uniqueness, so `effective_sample_size` could
only have been the training row count, which is precisely the quantity
UNIT-027 computes uniqueness to avoid. `uniqueness` is now a required
argument and a missing weight is refused rather than defaulted to one.

No `config/model.toml` exists and this unit could not have created one, so
thresholds arrive as frozen dataclasses. That is the same recorded gap
UNIT-013 and UNIT-017 already carry, not a new design.

### The dependency, and the rule it bends

D-027 records the addition of `numpy` and `scikit-learn`, the stdlib
alternative that was considered and rejected, and the fact that widening this
unit's globs onto `pyproject.toml` and `uv.lock` bends D-010. It was safe only
because UNIT-025 was the sole claimed unit at the time, with UNIT-027 and
UNIT-030 both merged and nothing else in flight. It is not a precedent.

### An error the contract names that cannot occur

The contract lists `UncalibratedModelError` for `predict` called before
calibration. That state is unreachable rather than guarded: `fit` is the only
way to obtain a `FittedModel` and it refuses to return one it could not
calibrate, so no uncalibrated model ever exists to be asked. The error is still
raised, from `fit`, which is AC-9. Making the invalid state unrepresentable is
stronger than checking for it at every use, and
`test_no_path_produces_a_model_that_has_not_been_calibrated` pins the property
so a later constructor cannot quietly reintroduce the gap.

### A defect found in this unit's own tests, by its own mutation probes

Two of the first six probes survived, and both were defects in the tests rather
than in the code. Recorded rather than quietly fixed, because both are the
shape `backtest-auditor` caught on UNIT-013: an assertion structurally
incapable of the failure it names.

The effective sample size test weighted every label at one half and asserted
sixty. Kish's effective sample size of any uniform weighting is exactly the row
count whatever the weight is, so that fixture agreed with the row count it was
written to detect, and replacing the entire computation with `len(weights)`
passed it. The fixture is now deliberately uneven, thirty labels at one and
thirty at a fifth, and asserts the hand-computed 36^2 / 31.2 as well as being
strictly under the row count.

The family attribution test moved a news feature and observed that the price
attribution held. A mutation dropping the feature value entirely, attributing a
bare coefficient, also holds under that observation. Two tests now pin it from
both sides: a family whose features are all zero attributes exactly zero, and
doubling a family's evidence doubles its contribution.

The trial ordering test had the same weakness and was rewritten before the
probes ran. It appended a marker after `fit` returned, which records the same
order however late registration happened. It now instruments `Ridge.fit`
through the module attribute, and a second test pins that the patch is not
inert.

### Verification actually run

`ruff check`, `ruff format --check` over 68 files, `mypy src` under strict
across 32 source files, 701 tests, and `scripts/verify_harness.sh` all green.
`uv sync --frozen` audits clean with the new dependencies.

Six mutations were run one at a time against the finished code, restoring the
file between each, and all six are caught: folding `fold_hash` into
`model_version`, dropping the refusal of supplied test-label features,
dropping the refusal of a fold whose own label lists overlap, replacing the
effective sample size with the row count, attributing a bare coefficient
instead of a coefficient against a value, and allowing a prediction inside the
window the model was fitted through.

That claim is bounded to these six against this unit's own changes. It is not a
statement about the suite as a whole, and the two survivors above are the
reason the distinction is worth drawing.

### Not done here, and named so it is not mistaken for done

No model has been fitted on real data. Every number in this unit comes from a
fixture with a known linear relationship, and the thresholds in
`EligibilityConfig` and `ModelConfig` are declared defaults, not selected on
development data, so design section 4's selection, registration, and freeze
remain untouched. `config_version` and `model_version` exist so that selection
is auditable when it happens.
