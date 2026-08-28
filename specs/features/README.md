# Feature specs

Work too large for a single unit starts here. One unit needs an intake in
`specs/units/`, not a spec.

```
specs/features/NNN-slug/
    spec.md        what is wanted and why          (spec-plot)
    analysis.md    findings, read-only             (spec-analyze)
    plan.md        how, and the unit boundaries    (spec-plan)
    tasks.md       optional narrative of the split (spec-tasks)
```

`spec-tasks` writes the real output into `specs/units/`, because that is what
`coord.py` claims, `dispatch.sh` sends, and `review.sh` gates. The feature
directory holds the reasoning; the registry holds the work.

The pipeline:

```
spec-plot -> spec-analyze -> spec-clarify -> spec-plan -> spec-analyze again
          -> spec-tasks -> dispatch.sh -> review.sh -> coord.py review -> merge
```

`spec-analyze` runs twice on purpose. The first pass reads the spec alone. The
second has the plan too, and can check the two against each other: anything the
plan adds that the spec never asked for, and anything the spec requires that
the plan ignores.

Nothing here replaces the unit intake. The point of planning ahead is to have
several units specified and dispatchable at once rather than one, so the
constraint that actually matters is the one `coord.py` enforces: units worked
in parallel must declare disjoint path globs.
