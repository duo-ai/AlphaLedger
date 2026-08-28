---
name: verification-loop
description: Use $verification-loop to run the AlphaLedger quality gate and report, before moving a unit to in_review, before a merge, and before claiming work is complete.
origin: AlphaLedger
---

# Verification loop in Codex

Evidence before assertions. This skill produces a report you can paste into a
review; it never claims a path is verified because it looked correct.

## When to use

- Before moving a unit to `in_review`.
- Before merging a `feature/` branch into `develop`.
- Any time you are about to say a change is done.

## Phase 1: environment

```bash
uv sync --frozen
```

A drifted lockfile invalidates every result below it. Stop here if this fails.

## Phase 2: lint and format

```bash
uv run ruff check .
uv run ruff format --check .
```

## Phase 3: types

```bash
uv run mypy src
```

Strict mode. Typed boundaries are a project rule, not a preference.

## Phase 4: tests

```bash
uv run pytest
```

Report the count. Paper integration tests are opt-in and must not appear in the
default run; if you see a network call here, that is a defect.

## Phase 5: secrets

```bash
git diff --cached --name-only | xargs -r grep -lnE 'ALPACA_(API|SECRET)_KEY\s*=' || echo clean
grep -rn "sk-\|secret_key\s*=" --include="*.py" src tests || echo clean
```

Report the variable name only. Never print a value, and never paste one into a
report, a log, or a commit.

## Phase 6: paper isolation

```bash
grep -rn --include="*.py" "api.alpaca.markets" src | grep -v "paper-api" || echo clean
grep -rnE --include="*.py" -e "--live" -e "paper[[:space:]]*=[[:space:]]*False" src || echo clean
```

Any hit is blocking. The live host must be absent from `src`, not merely
unused.

## Phase 7: harness

```bash
bash scripts/verify_harness.sh
```

Covers the guards, the registry, the branching model, and the hooks firing
inside a worktree.

## Phase 8: diff

```bash
git diff --stat
git diff origin/develop...HEAD --name-only
```

Read every changed file for unintended edits, missing error handling, and
edge cases the test list did not name.

## Report

```text
VERIFICATION REPORT
===================
Environment   [PASS/FAIL]  uv sync --frozen
Lint          [PASS/FAIL]  ruff check, ruff format
Types         [PASS/FAIL]  mypy strict, N errors
Tests         [PASS/FAIL]  N passed, N failed
Secrets       [PASS/FAIL]  N findings
Paper isolate [PASS/FAIL]  live host absent from src
Harness       [PASS/FAIL]  N checks
Diff          N files changed

Overall       [READY / NOT READY] for review

Commands actually run:
  ...
Not verified:
  ...
```

The last two blocks are required. Per the project contract, a report states
which commands were actually run and what remains unverified. Never call a path
verified when it was only inspected.
