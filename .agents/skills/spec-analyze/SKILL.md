---
name: spec-analyze
description: Use $spec-analyze to read a spec adversarially for ambiguity, unfalsifiable criteria, and conflicts with the project's own rules, and record the findings. Use after spec-plot and again after spec-plan.
origin: AlphaLedger
---

# Analyze a spec in Codex

Read-only. This step finds problems and writes them down; `spec-clarify`
resolves them. Keeping those apart matters, because an author who can fix a
finding on sight will rationalise it instead of recording it.

Run it after `spec-plot`, and again after `spec-plan` once the plan exists, at
which point the cross-artifact checks below have something to compare.

## Output

`specs/features/NNN-slug/analysis.md`, a table of findings and then the
coverage summary. Do not edit the spec.

## Six passes

**Ambiguity.** Adjectives doing load-bearing work with nothing behind them:
fast, robust, scalable, secure, reliable, appropriate, correct. Each one is a
finding unless a numbered criterion defines it.

**Unfalsifiable criteria.** For every success criterion, name the observation
that would falsify it, then ask whether that observation is physically
available at the point the criterion applies. This is the pass that matters
most here. UNIT-010 shipped a criterion requiring a redirect to be rejected
before the request body was sent; a redirect is a response, so the body has
necessarily already gone, and the criterion could never be met by anything.
The test list then reproduced the false premise rather than catching it,
because the same author wrote both.

**Underspecification.** A requirement that two competent readers would
implement differently. Mark it and say what the two readings are. If the spec
carries a `[NEEDS CLARIFICATION]` marker here already, that is not a finding,
it is the author doing this correctly.

**Conflict with the project's own rules.** Read `AGENTS.md`, the
`.claude/rules/` file matching the paths this will touch, and
`project-state/DECISIONS.md`. A spec that contradicts an accepted decision is a
CRITICAL finding and the answer is to change the spec or amend the decision,
never to reinterpret the decision quietly.

**Coverage.** Every outcome traces to at least one success criterion, and every
criterion traces to something in scope. A criterion with nothing in scope
behind it means the scope is wrong or the criterion is aspirational.

**Consistency.** Terminology that drifts between sections, an entity named in
one place and absent elsewhere, a scope line contradicting a criterion. After
`spec-plan` exists, add: anything the plan names that the spec never asked for,
and anything the spec requires that the plan does not address.

## Severity

- **CRITICAL**: contradicts a rule in `AGENTS.md`, a `.claude/rules/` file, or
  an accepted decision. Also a success criterion that cannot be observed.
- **HIGH**: two readings with materially different implementations; a
  requirement with no criterion; a criterion with no scope behind it.
- **MEDIUM**: terminology drift, an untraced outcome, a vague adjective.

## Finish by

Reporting counts by severity and, plainly, whether the spec is fit to plan
from. "Three MEDIUM findings, fit to plan" is a real answer. So is "one
CRITICAL, not fit to plan until resolved".

Then run `spec-clarify` if anything is CRITICAL or HIGH.

## The honest limit

If the same reasoning that wrote a bad criterion also runs this pass, it will
tick its own box. This step raises the odds of catching an error; it does not
make catching it certain. That is why a specialist reviewer still reads the
work afterwards, and why the two are not the same step.
