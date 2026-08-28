---
name: tdd-workflow
description: Use $tdd-workflow to drive a claimed unit from its test list to a passing quality gate, when implementing any unit, bugfix, or refactor.
origin: AlphaLedger
---

# TDD workflow in Codex

Tests come from the unit intake, not from imagination. The `## Test list`
section of `specs/units/<unit>.md` was written before the unit became
claimable, which means the specification of correct behaviour already exists.
This skill turns that list into failing tests, then into passing code.

## When to use

- Implementing a claimed unit.
- Fixing a defect, where the first step is a test that reproduces it.
- Refactoring, where the tests must already pass and must keep passing.

## Step 0: read the contract

```bash
python3 scripts/coord.py show UNIT-0NN
```

If the unit is unclaimed, claim it. `coord.py` already refuses a unit
someone else holds and one whose dependencies are unmerged, so the lock is
real. Then work inside its worktree, never in the primary clone. Read
`## Contract`, `## Acceptance criteria`, and `## Test list`. If the test list is
thin, fix the intake first and commit that separately. Implementing against a
vague spec is how a unit ends up untestable.

## Step 1: write the tests

One test per line of the test list. Per `.claude/rules/40-tests.md` the name
states the invariant and the failure condition, not the function name:

```python
def test_naive_event_time_is_rejected_and_the_message_names_the_field() -> None:
```

The list covers four paths and so must the tests: success, failure, restart,
and no-trade. A unit whose no-trade path is untested is not done, because
`no_trade` is a valid and expected result in this system.

Research units additionally need a deliberately leaked fixture that the
pipeline must reject, per `.claude/rules/20-research-integrity.md`.

## Step 2: red

```bash
uv run pytest tests/<area> -q
```

The tests must fail, and they must fail for the reason you expect. A test that
passes before the implementation exists is testing nothing. A test that errors
on an import is not yet a red test; make it fail on an assertion.

## Step 3: green

Write the minimum that satisfies the tests. Do not add fields, options, or
abstractions the test list does not require.

If a test is hard to satisfy, change the code. Never weaken the test, relax an
assertion, or delete a case to reach green. If the test itself is wrong, say so
explicitly and correct the intake first.

## Step 4: refactor

Tests stay green throughout. Behaviour does not change.

## Step 5: the gate

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest
```

All four pass before the unit moves to `in_review`. Use `$verification-loop`
for the full report including the secret and paper-isolation scans.

## Step 6: hand over

```bash
python3 scripts/coord.py state UNIT-0NN in_review
```

Request the reviewer named in the unit frontmatter. Reviewers report; they do
not edit files.

## What this skill will not do

- Merge anything. A `feature/` branch merges after its named reviewer reports.
- Lower a coverage or quality bar to finish faster.
