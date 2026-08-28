---
id: UNIT-024
title: Split chronologically and register every trial
lane: research
state: in_review
owner: mazwy/claude
branch: feature/024-splits-and-trial-registry
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001]
paths: src/alphaledger/forecast/__init__.py, src/alphaledger/forecast/splits.py, src/alphaledger/forecast/registry.py, tests/research/test_splits.py, tests/research/test_registry.py
claimed_at: 2026-08-28T20:53:56Z
---

## Problem

A model fitted before this exists cannot produce an honest number. Two
disciplines have to be in place first, and both are ordering constraints rather
than features: a trial must be registered before anyone looks at its result, or
the registry records only the variants that happened to work; and windows must
be chronological and purged by at least the forecast horizon, or an overlapping
label leaks the outcome into the fit. Neither can be retrofitted, because by
the time a result exists the registry has already lost the trials that were
abandoned and the fit has already seen the leak.

This unit therefore precedes the model deliberately. It is the reason the
model's number will mean anything.

## Source of truth

- `options-alpha-agent-design.md` section 7, dataset split and trial registry.
- `options-alpha-agent-design.md` section 6, the horizon the purge is measured
  against.
- `.claude/rules/20-research-integrity.md`.

## Scope

In:

- an expanding chronological walk-forward producing, per fold, a training
  window, a calibration window, and a locked test window in that time order;
- a purge of at least the forecast horizon between adjacent windows, and an
  embargo that drops a label whose outcome window crosses a boundary;
- refusal to build a split whose purge is shorter than the horizon;
- an append-only trial registry recording the configuration hash, the stated
  purpose, and the registration instant;
- refusal to attach a result to a trial that was not registered first;
- a trial count, so a later stage can raise the multiple-testing warning
  section 7 requires.

Out:

- the pooled forecast model and the `Forecast` record it emits (UNIT-025).
- baselines, ablations, and metrics (UNIT-026). The registry counts trials; it
  does not judge them.
- any storage shared with the observation store. This registry is its own file
  and does not reuse `alphaledger.data.storage`, which belongs to UNIT-020.

## Contract

`alphaledger.forecast.splits.walk_forward(observations, config) ->
tuple[Fold, ...]` where a `Fold` carries the three windows, the horizon, the
purge applied, and a content hash. Pure, deterministic, no clock read.

`alphaledger.forecast.registry.TrialRegistry` is append-only, with
`register(configuration, purpose) -> TrialId` and
`record_result(trial_id, result)`. `record_result` refuses an unknown
`TrialId`. Reads report every trial ever registered, including abandoned ones.

Both raise rather than degrade. A split that cannot be purged correctly and a
result that cannot be tied to a registration are the two failures that make a
final number unfalsifiable, so neither is recoverable in place.

## Acceptance criteria

- AC-1: within every fold, the training window ends before the calibration
  window begins and the calibration window ends before the locked test window
  begins, with no timestamp shared across a boundary.
- AC-2: the gap between adjacent windows is at least the forecast horizon, and
  a configuration with a shorter purge is refused at construction.
- AC-3: a label whose outcome window crosses a window boundary is excluded and
  named, rather than assigned to whichever side it started in.
- AC-4: `record_result` refuses a `TrialId` that was never registered.
- AC-5: the registry is append-only across a restart, and a previously
  registered trial with no result is still reported.
- AC-6: building the same split twice from the same inputs yields the same
  fold hashes.

## Test list

- success: a fixture of observations produces the expected fold boundaries, and
  rebuilding yields identical hashes.
- success: an expanding walk-forward grows the training window fold over fold
  while the test window moves forward and never overlaps a previous one.
- failure: a purge shorter than the horizon is refused at construction, naming
  both values.
- failure: a label whose outcome window crosses a boundary is excluded and
  named. This is the leaked fixture the research rules require.
- failure: a training window containing a timestamp at or after its own
  calibration window start is refused rather than trimmed silently.
- failure: `record_result` on an unregistered trial is refused, naming the id.
- restart: a registry reopened in a separate process reports every trial the
  first process registered, including one that was registered and abandoned
  without a result, and appending does not rewrite prior entries.
- no-trade: a period too short to produce a single valid fold yields an empty
  tuple of folds with the reason recorded, not a fold with a relaxed purge.
- no-trade: an empty registry reports zero trials rather than failing.

## Verification

```bash
uv run pytest tests/research/test_splits.py tests/research/test_registry.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

`splits.py` builds the expanding walk-forward and decides which labels each
window may use. `registry.py` records every attempt before it has a result.

### Two deviations from this intake, both deliberate

The contract line said `walk_forward(...) -> tuple[Fold, ...]`, but the
no-trade criterion asks for the reason a span produced no folds, and a tuple
carries no reason. It returns a `WalkForward` holding `.folds` and `.reasons`.
The alternative, raising when no fold fits, would make an empty split an error,
and an empty split is an answer.

The scope said the registry does not reuse `alphaledger.data.storage`. It does.
The rule was written to stop two units sharing one file, and that still holds:
this registry writes its own file. Reuse here imports a module UNIT-020 already
built and tested, corruption behaviour included, and duplicating an append-only
writer would have created a second corruption implementation to keep in sync.
The import is not read-only, since `register` and `record_result` both append;
what it does not do is share or modify UNIT-020's file.

### The rule that does the work

A label is usable in a window only when both its prediction and its outcome
fall inside it. A prediction near a boundary whose outcome resolves after it is
excluded and named `outcome_crosses_boundary`, never trimmed or reassigned, and
a prediction inside a purge gap is excluded as `in_purge_gap`. A configuration
whose purge is shorter than the horizon is refused at construction rather than
at use, because by the time a fold exists the caller is already reasoning about
results.

The registry refuses two things rather than accommodating them: a result for a
trial nobody registered, and a second result over an existing one. The second
matters as much as the first, since overwriting is how a disappointing result
quietly becomes a better one.

### Verified

- `uv run pytest tests/research/test_splits.py tests/research/test_registry.py -q`:
  33 passed.
- `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy src`,
  `pytest`: all pass, 209 tests.
- The restart test spawns real subprocesses and asserts that an abandoned trial,
  registered with no result, survives and that earlier bytes are a prefix.
- Eighteen defects were injected one at a time. Four survived the first pass and
  each exposed a real weakness rather than a false alarm: the overlap check is
  subsumed by the gap check unless the message is asserted, the declared purge
  was not pinned in the fold hash independently of the windows it moves, the
  duplicate-registration test passed because reading collapses duplicates by id
  so a growing log was invisible, and the float refusal was satisfied by a
  generic type error. All four now have assertions that separate them.

### Review round one, backtest-auditor

Two high findings, both real, both fixed.

- `walk_forward` built every fold it was asked for when `available_until` was
  omitted, whatever the data covered, and recorded no reason. Three structurally
  valid, hashed folds over a span with data in only the first one is not three
  results, and a later stage averaging across "three folds" would have been
  averaging one real fold and two built out of nothing. `available_until` is now
  required, so a caller has to state the span it has. Separately, a fold whose
  test window holds no label while the label series holds something is now
  reported, which catches a span that is merely too generous rather than absent.
  Every no-trade test had supplied the argument, and every assignment test
  destructured the first fold only, so the empty later folds were already the
  fixtures' normal state and nothing looked at them.
- The registry enforced register-before-result and no-overwrite at the write
  call and nowhere on read, so a duplicate result on disk was resolved by
  reading order, last one winning, and an orphan result vanished from every
  count. Two processes can both pass the write-time check before either appends,
  and the unit's own restart tests spawn concurrent processes against one file,
  so this was not a corrupted-file edge case. Both now raise on read. Taking the
  last result would have been the overwrite this registry exists to prevent,
  arriving by another route.
- Two low findings, both fixed. The float refusal was exercised only through
  `record_result`, though one validator serves both arguments, and only one of
  the two purge gaps had a fixture.

The reviewer confirmed by construction that a label predicted before a window,
and a label spanning a whole window, are both handled, and that the classic
overlapping-label problem inside a single window is a sample-size concern
belonging to `effective_sample_size`, not to the purge. Both declared deviations
were accepted, with the wording nit above.

Twenty-three defects were injected one at a time after these fixes and every one
is caught by a named test.

### Review round two, backtest-auditor

One new high finding, which is round one's own fix reappearing one window to
the left, plus two low ones.

- The `empty_test_window` reason had no calibration counterpart, and
  `SplitConfig` related nothing but the purge to the horizon. A calibration
  window no longer than the horizon can only hold a label predicted at its very
  first instant, so it purges every other candidate, and a fold with a populated
  test set and an empty calibration window was reported entirely clean. Design
  section 7 names calibration as its own required step, so such a fold has no
  way to have chosen a threshold. Both windows are now validated against the
  horizon at construction, which refuses the whole family before a fold exists,
  and an `empty_calibration_window` reason mirrors the test one for the case
  where the window is long enough but the data does not reach it.
- The reason string did not distinguish a window nothing was predicted in from
  one whose candidates were all purged. Those are a data gap and a geometry
  problem, and they call for different fixes, so the message now says which and
  how many.
- The all-folds-empty case, which round two flagged as chosen but unpinned, now
  has a test. Suppressing the reason when every fold is empty would silence it
  exactly where the configuration is most wrong for the data supplied.

A binding in the new reason loop shadowed the assignment tuple. `mypy` caught
it; the pipeline that ran it did not, because a pipe swallowed the exit code,
and the commit landed before the check was read. That is a hazard in how the
gate was run, not in the gate.

Twenty-six defects were injected one at a time after these fixes and every one
is caught by a named test.

### The race this unit detects but does not prevent

`record_result` refuses a second result, but two processes can both pass that
check before either appends, and `AppendOnlyStore.append` takes no lock. Round
one's fix makes the resulting log raise on read rather than resolving it by
reading order, so the failure is loud and fail-closed: every later read, and
every later `register`, refuses until a human looks.

The reviewer suggested an advisory lock around the check-and-append, which would
sit in this unit's own file. It is not done here, deliberately. A lock is only
worth having if it is tested, a deterministic concurrency test needs either a
sleep, which `.claude/rules/40-tests.md` forbids, or a synchronisation
mechanism this unit has no other reason to own, and untested concurrency code in
an audit path is its own risk. The detection is in place and disclosed; the
prevention should be its own unit if concurrent research runs become real.

### Not verified

- No model consumes a fold and no result is ever recorded, so the registry is
  proven to refuse what it should and never proven against a real research run.
- The walk-forward is time based. It does not consult an exchange calendar, so
  a horizon expressed in sessions has to be converted by the caller. UNIT-025
  should decide whether that conversion belongs here.
- Nothing computes the multiple-testing warning section 7 asks for. This unit
  provides the count it needs and stops there.

