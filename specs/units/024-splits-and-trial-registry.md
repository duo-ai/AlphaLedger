---
id: UNIT-024
title: Split chronologically and register every trial
lane: research
state: claimed
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
