---
name: spec-plan
description: Derive how a spec will be built, including the file layout and the unit boundaries, without writing any code. Use after the spec is analysed and clarified.
origin: AlphaLedger
---

# Plan

The spec says what and why. The plan says how, and its main product is the
boundary between units, because that boundary is what makes parallel work safe
or unsafe.

Do not plan from an unanalysed spec. Run `spec-analyze` first, and
`spec-clarify` if it found anything CRITICAL or HIGH.

## Where it goes

`specs/features/NNN-slug/plan.md`, beside the spec it derives from.

## What a plan contains

**Approach.** Two or three paragraphs on how this will be built, and one
paragraph on the approach you rejected and why. The rejected option is what
stops the next reader relitigating it.

**Existing surface it builds on.** What already exists that this must use
rather than rebuild, named exactly. A plan that silently reimplements something
merged is the most expensive kind of wrong.

**Package before bespoke.** `AGENTS.md` requires naming the established package
that already solves a problem before hand rolling it. Do that here, per
component, and say why it does or does not fit. "Nothing suitable" is a fine
answer once you have named what you looked at. Note the standing exception:
code that must run before the environment exists is standard library only, and
saying so is not reinvention.

**File layout.** The concrete paths this creates or changes, under `src/` and
`tests/`. Be exact. This is the list that becomes each unit's `paths`, and
`coord.py` refuses to claim a unit that names a file its paths forbid, so
vagueness here becomes a refused claim later.

**Unit boundaries.** The decomposition, with the discriminator you used. A good
discriminator is one an implementer can apply per function without asking:
"does it need a clock, a broker response, or prior state" cleanly separates a
pure mapping from a lifecycle. Say the discriminator, not just the result.

For each proposed unit: its lane, the files it owns, what it depends on, and
which reviewer gates it. Path globs across units must be disjoint, because that
is exactly what `coord.py` enforces at claim time and what makes them
dispatchable in parallel.

**Sequencing.** What must merge before what, and why. Prefer a real dependency
over a preference: `depends_on` is mechanical, and a spurious one serialises
work that could have run at once.

**Risks.** What could make this plan wrong. Not a ritual list; the two or three
things you would actually bet on going differently.

## What a plan does not contain

Code, test bodies, or acceptance criteria. Criteria belong to the spec, tests
to the unit intake. A plan that writes tests has skipped `spec-tasks` and taken
the decomposition decision implicitly.

## Finish by

Re-running `spec-analyze`, which now has both artifacts and will check them
against each other: anything the plan adds that the spec never asked for, and
anything the spec requires that the plan ignores.

Then run `spec-tasks`.
