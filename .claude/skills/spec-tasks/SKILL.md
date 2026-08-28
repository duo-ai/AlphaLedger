---
name: spec-tasks
description: Turn a plan into claimable unit intakes that the registry and the dispatcher can act on. Use after spec-plan, as the last step before work starts.
origin: AlphaLedger
---

# Tasks

This is where the pipeline rejoins the machinery. A task here is not a checkbox
in a list: it is a unit intake in `specs/units/`, which `coord.py` can claim,
`dispatch.sh` can send to Codex, and `review.sh` can gate. Everything the
project already enforces starts working the moment these files exist.

## Write one intake per unit boundary

Use `specs/TEMPLATE.md`. The plan already decided the boundaries and the file
layout; this step turns each into a claimable file. If you find yourself
redeciding a boundary here, the plan was not finished.

Number units by lane, matching what is already there: `0NN` shared, `01N`
execution, `02N` research.

## The fields that are mechanical, not descriptive

Four pieces of frontmatter are enforced, so getting them wrong shows up as a
refused claim rather than a comment:

- `paths`: every file this unit creates or changes. `coord.py` refuses a claim
  when the body names a file the paths forbid, and refuses two in-progress
  units whose globs overlap. Copy these from the plan's file layout; do not
  re-derive them.
- `depends_on`: only real dependencies. Each one serialises work, and a
  spurious one costs a parallel dispatch.
- `reviewer`: the specialist that gates the merge. Execution units go to
  `execution-safety-reviewer`, research to `backtest-auditor`, shared to
  `code-reviewer`.
- `preferred_runtime`: `codex` for implementation-heavy work, which is the
  standing default, `claude` where the unit is small or entangled with a
  judgement call.

## The test list is the specification

Write it before any implementation exists. Four paths, every unit: success,
failure, restart, and no-trade. A unit whose no-trade path is untested is not
finished, because an empty result is a first-class outcome here.

Each name states the invariant and the failure condition, not the function
name. And for each test, ask what would have to break for it to fail. If the
answer is nothing in the code under test, the test is theatre. A recording
double that cannot exhibit the failure its test is named for will pass forever;
that exact defect shipped in UNIT-010 and took a specialist reviewer to find.

Research units additionally need a deliberately leaked fixture the pipeline
must reject, per `.claude/rules/20-research-integrity.md`.

## Say what you do not know

If a unit cannot be specified without a decision nobody has made, write
`[NEEDS CLARIFICATION: the question]` in the section where the gap sits.
`coord.py` will refuse to claim it, which is correct: the unit is not ready.
Inventing an acceptance criterion to fill the hole is the failure this marker
exists to prevent, and an invented criterion reads exactly like a considered
one.

## Finish by

Checking the decomposition is actually dispatchable:

```bash
bash scripts/hook_python.sh scripts/coord.py list
bash scripts/dispatch.sh UNIT-0NN UNIT-0NM pablo/codex --dry-run
```

The dry run refuses a batch whose globs overlap, before anything is claimed.
That is the answer to whether the plan's boundaries were real.

Then dispatch. `scripts/dispatch.sh` for Codex, the Agent tool with worktree
isolation for Claude, `scripts/review.sh` when the work lands, and
`coord.py review` to record the verdict that lets it merge.
