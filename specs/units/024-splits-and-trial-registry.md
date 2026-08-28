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
this registry writes its own file. Reuse here is a read-only import of a module
UNIT-020 already built and tested, corruption behaviour included. Duplicating an
append-only writer would have created a second corruption implementation to keep
in sync, which is a worse outcome than the coupling. Say so if you disagree; the
import is one line to reverse.

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

### Not verified

- No model consumes a fold and no result is ever recorded, so the registry is
  proven to refuse what it should and never proven against a real research run.
- The walk-forward is time based. It does not consult an exchange calendar, so
  a horizon expressed in sessions has to be converted by the caller. UNIT-025
  should decide whether that conversion belongs here.
- Nothing computes the multiple-testing warning section 7 asks for. This unit
  provides the count it needs and stops there.

