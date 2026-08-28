---
id: UNIT-000
title: one line, imperative, no trailing period
lane: shared
state: available
owner: -
branch: -
reviewer: code-reviewer
preferred_runtime: codex
depends_on: []
paths: src/alphaledger/<area>/**
---

## Problem

One paragraph. What is missing, and what breaks or stays unprovable without it.
No solution here.

## Source of truth

Exact anchors only, never restated content:

- `options-alpha-agent-design.md` section N
- `hackathon-build-plan.md` section N
- `.claude/rules/<file>.md`

If a rule already states an invariant, cite it. Copying it here creates a
second copy that will drift.

## Scope

In:

- the specific behaviour this unit delivers

Out:

- what a reader might reasonably expect here but which belongs to another unit,
  named by id

## Contract

The public interface other units may depend on. Typed signatures, the domain
objects consumed and produced, and the errors raised. Reference the frozen
dataclasses in design section 14 rather than redefining them.

## When you do not know

Write `[NEEDS CLARIFICATION: the question]` inline, in the section where the
gap sits. `coord.py` refuses to claim a unit that still carries one, so an open
question blocks work rather than being quietly resolved by whoever implements.

Use it when a choice changes scope, safety, or what the unit is for. Below that
bar, decide, and record the decision under `## Assumptions` instead. Three
markers is the practical ceiling: more than that means the unit is not ready to
be specified, not that it needs more markers.

This exists because the alternative is worse. An author who does not know and
has no way to say so invents an acceptance criterion, and an invented criterion
reads exactly like a considered one. UNIT-010 shipped an AC that was
unsatisfiable in principle, and its test list then faithfully reproduced the
false premise.

## Assumptions

Decisions taken where the intake could reasonably have gone another way, one
line each. A reader who disagrees with the unit should be able to find the
choice here rather than reverse-engineering it from the code.

## Acceptance criteria

- AC-1: behavioural, observable, and testable. Not "handles errors well".
  For each one, name the observation that would falsify it, and check that
  observation is physically available at that point. An AC nothing can
  observe is worse than a missing one, because it looks satisfied.
- AC-2: ...

## Test list

Written before implementation. This section is what makes the unit claimable.

Per `.claude/rules/40-tests.md`, each name states the invariant and the failure
condition. Per the definition of done in `AGENTS.md`, the list covers all four
paths:

- success: ...
- failure: ...
- restart: ...
- no-trade or empty result: ...

## Verification

The exact commands that must pass before this unit moves to `in_review`:

```bash
uv run pytest tests/<area> -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

Append only. Newest last. One line per entry, prefixed with the date and the
owner. Anything longer belongs in a commit message on the feature branch.
