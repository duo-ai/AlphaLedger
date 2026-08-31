---
id: UNIT-006
title: Add the pinned HTTP client the order path needs
lane: shared
state: available
owner: -
branch: -
reviewer: code-reviewer
preferred_runtime: claude
depends_on: []
paths: pyproject.toml, uv.lock, tests/test_dependencies.py
---

## Delegated to mazwy

Assigned to `mazwy` on 2026-08-31 by the user, together with the other five
units of feature 001. These are execution lane paths rather than research ones,
so the roster in `AGENTS.md` is amended to record the exception rather than
leaving it to be inferred. `preferred_runtime` is `claude` because that is the
runtime the owner runs, and `scripts/dispatch.sh` refuses a Claude owner by
design, so these are claimed and worked in a session with worktree isolation
rather than dispatched.

## Blocked

[NEEDS CLARIFICATION: C7. AC-4 and the test list forbid every `httpx` import repository wide, but UNIT-031 must add one and its declared paths exclude this unit's test file, so the gate cannot pass inside UNIT-031's boundary. Recorded 2026-09-01 from the Codex analysis pass in
`specs/features/001-autonomous-session/analysis-codex.md`, which found seven
CRITICAL and five HIGH findings that five earlier passes missed. A fix pass was
started and stopped before it completed, and its partial edits were discarded
rather than shipped half applied, so every finding below is open. Do not claim
this unit until it is resolved and this marker is removed.]

## Problem

`src/alphaledger/broker/endpoint.py` declares `PaperTransport` and no
implementation exists, because the project carries no HTTP client. `httpx`
appears zero times in `pyproject.toml` and `uv.lock`, verified on 2026-08-31.

This is two lines and it blocks five units, so it is its own unit rather than a
widening of one of theirs. D-027 widened UNIT-025's globs onto the lockfile,
recorded that this bends D-010, and said plainly that it is not a precedent.
Repeating a bend its own author labelled unrepeatable needs a better argument
than convenience, and here there is none: the change can simply land first.

## Source of truth

- `specs/features/001-autonomous-session/plan.md`, the Package before bespoke
  and File layout sections.
- `project-state/DECISIONS.md`, D-027 and D-012.
- `AGENTS.md`, the instruction to prefer a well established package and to pin
  whatever is added.

## Scope

In:

- `httpx`, pinned exactly, in `pyproject.toml`.
- The resulting `uv.lock` update.

Out:

- Any use of it. This unit adds the dependency and imports it nowhere.
  UNIT-031 is the first caller.
- Any other dependency. A lockfile change that carries a second package is a
  different change and would reopen the D-010 question this unit exists to
  avoid.

## Contract

`pyproject.toml` gains `httpx` at an exact pin, in the existing `dependencies`
list beside `numpy` and `scikit-learn`, with a comment naming the unit that
needs it in the style D-027 already used there.

Choose the version by resolving it, not by copying one from memory, and record
the resolved version in the handoff notes with the command that produced it.

## Acceptance criteria

- AC-1: `httpx` is pinned to an exact version, not a range. Falsified by any
  specifier other than `==`, which would let a later resolve change the client
  on the order path without a commit.
- AC-2: `uv sync --frozen` succeeds and audits clean afterwards. Falsified by a
  sync that reports the lockfile out of date, which would mean the lock and the
  manifest disagree.
- AC-3: `httpx` imports on cp314 in this environment. Falsified by an import
  error, which is the thing D-012 checks for every dependency before anything
  relies on it.
- AC-4: no source file imports `httpx`. Falsified by any import outside
  `pyproject.toml` and `uv.lock`, because this unit is the dependency and not
  its first use.
- AC-5: the repository quality gate passes unchanged. Falsified by any test,
  lint, or type failure introduced by the dependency being present.

## Test list

`tests/test_dependencies.py`, new. An earlier draft of this intake said there
was no test file and left the verification to manual commands, which the
harness correctly refused: a unit that cannot write its own tests cannot prove
its own claim, and AC-1 and AC-3 are both testable.

- success: `httpx` imports, and the imported module is the version
  `pyproject.toml` pins, compared against the file rather than against itself.
- failure: every dependency in `pyproject.toml` uses an exact `==` pin,
  parameterised across the list so a later range on any package fails, not only
  on `httpx`.
- failure: no module under `src/` imports `httpx`, which pins AC-4 and would
  fail the moment UNIT-031 lands, at which point that assertion moves to
  UNIT-031's intake rather than being deleted here.
- restart: the pinned version is read from `pyproject.toml` in a subprocess and
  matches the installed one, so the lock and the environment are proven to
  agree rather than assumed to.
- no-trade: the test module imports nothing from `alphaledger`, so it passes in
  a checkout where the application does not import at all, which is the state a
  dependency change has to be verifiable in.

## Verification

```bash
uv sync --frozen
uv run pytest tests/test_dependencies.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q
bash scripts/verify_harness.sh
```

## Handoff notes
