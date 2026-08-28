---
name: spec-plot
description: Write a feature spec that says what is wanted and why, before anything decides how. Use when starting work larger than a single unit.
origin: AlphaLedger
---

# Plot a spec

A spec is for work too large to be one unit. One unit needs an intake, not a
spec. If what you are describing fits in a single `specs/units/` file with one
contract and one test list, stop and write that instead.

The pipeline this starts:

```
spec-plot -> spec-analyze -> spec-clarify -> spec-plan -> spec-tasks
          -> dispatch.sh   -> review.sh    -> coord.py review -> merge
```

Each step has its own skill. Do not skip forward: `spec-tasks` produces unit
intakes that `coord.py` will refuse if they are underspecified, so a weak spec
surfaces later and more expensively.

## Where it goes

`specs/features/NNN-slug/spec.md`, where NNN is the next free number. The
feature directory will also hold `analysis.md`, `plan.md`, and `tasks.md` as
the later steps run.

## What a spec contains

Write these sections and nothing else. Anything that does not fit one of them
is either a plan detail or an assumption.

**Problem.** What is missing or wrong today, and what stays impossible or
unprovable without this. No solution.

**Outcome.** What is true when this is done, stated so someone else could
decide whether it happened. Not "improve the recorder"; rather "a feature built
from a given `as_of` is reproducible byte for byte in another process".

**Scope.** In and out, by name. The out list is the more useful half: it is
where a reader learns what you already considered and rejected.

**Constraints that are not negotiable.** Cite them, do not restate them.
`AGENTS.md` for the safety boundary, `.claude/rules/` for the path-scoped
invariants, `project-state/DECISIONS.md` for accepted choices. If this feature
would violate one, say so here rather than discovering it in review.

**Success criteria.** Numbered, observable. For each one name the observation
that would falsify it. This project's invariants are frequently type-shaped, so
"no `paper: bool` exists anywhere in the signature" is a legitimate criterion
even though it names a construct. Do not launder it into vagueness to sound
implementation-neutral.

**Open questions.** Write `[NEEDS CLARIFICATION: the question]` inline in the
section where the gap sits. Three is the practical ceiling. Below the bar of
"changes scope, safety, or what this is for", decide and record it under
Assumptions instead.

**Assumptions.** Decisions taken where it could reasonably have gone another
way, one line each.

## What a spec does not contain

File layouts, module names, function signatures, task ordering, or which
runtime implements it. Those are `spec-plan`'s job, and putting them here makes
the spec look settled in places it is not.

The one exception is the constraint above: where an invariant is genuinely
about shape rather than behaviour, state it. The distinction is whether the
detail is load bearing for correctness or merely one way to do it.

## Finish by

Reading it once as someone who disagrees with the feature. If you cannot find a
sentence they would argue with, it is probably too vague to be wrong, which
means it is too vague to implement.

Then run `spec-analyze`. Do not write the plan from an unanalysed spec.
