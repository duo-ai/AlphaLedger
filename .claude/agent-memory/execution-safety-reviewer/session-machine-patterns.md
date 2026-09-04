---
name: session-machine-patterns
description: Recurring defect shapes found reviewing closed-table state machines in AlphaLedger's execution lane (UNIT-012, UNIT-033, and likely UNIT-034/UNIT-035).
metadata:
  type: feedback
---

Two patterns worth checking on every future closed-table state machine review
(UNIT-034, UNIT-035, and any later revision of UNIT-012 or UNIT-033).

## An escalation recorded in a code comment and a unit intake is not the same as recording it where the comment claims

UNIT-033 round one found `Closed -> Halted` missing and graded it HIGH; round
two's fix left it deliberately unresolved and escalated it, with a comment in
`session.py` and prose in the unit intake's Handoff notes saying the decision
"belongs to whoever owns `specs/features/001-autonomous-session/spec.md`."
Checked `spec.md` directly on that branch: its one `## Clarifications` entry
predates the round-one review and says nothing about this question anywhere.
The escalation is real and the code behavior is fail-closed (the illegal pair
raises), but the authoritative feature document a future reader would consult
to judge whether feature 001 is ready to proceed carries no trace of the open
question, only the module comment and the intake do. Graded MEDIUM,
non-blocking for the unit itself (the fix belongs to a file outside the unit's
own path globs), but worth naming precisely rather than trusting the comment's
own claim about where it's recorded.

**How to apply:** when a unit escalates rather than resolves a finding, and
the escalation names a document as the decision's home, open that document and
check the claim rather than accepting prose that asserts it. Do this even when
the comment is well-written and the reasoning sounds right; a comment can be
correct about *what* was decided and wrong about *whether it's discoverable*.

## Check every state for a symmetric escape edge, not just the ones the source names

UNIT-033 authorized `Exiting -> Halted` on the grounds that a flatten can fail
and the design diagram gives `Exiting` nowhere to put that fact, citing
`.claude/rules/01-safety.md` bullet 4's "no exception" language. The same
module left `Closed -> Halted` absent. `Closed` returns to `Ready` on its own
edge, and `Ready` accepts `Halted`, so `Closed` is two hops from permitting a
new entry and one hop short of being able to record a halt directly. Nothing
in the source material exempts `Closed` from the same reasoning that justified
the `Exiting` addition; the asymmetry was undocumented.

**Why:** the reasoning that adds one deviation edge from a cited source
generalizes to every other state satisfying the same predicate. A reviewer who
accepts the cited justification for edge A must independently check every
other state against the same justification, not just the one state the intake
already flagged.

**How to apply:** for any closed-table machine, list every non-terminal state
and ask "does the authorized rationale for edge X also apply here?" before
accepting the table as complete. Do this even when the intake's own Handoff
notes present the table as settled and injected-and-reverted mutations as
proof of coverage; mutation testing proves the tests catch a *removed* edge,
not that a *needed* edge was never added.

## An immutability test on `MappingProxyType(...)` proves less than it looks like

`MappingProxyType({...})` built from an anonymous literal has no other handle
to the underlying dict, so a test that mutates through the proxy and expects
`TypeError` is currently sound. But if the dict literal is ever hoisted to a
named variable (`_TABLE = {...}; LEGAL_TRANSITIONS = MappingProxyType(_TABLE)`)
for any refactor reason, the same test keeps passing while
`session._TABLE[key] = value` mutates the "frozen" table at runtime with no
`TypeError` anywhere.

**Why:** `MappingProxyType` is a read-only *view*, not an immutable copy. A
test against the view alone cannot distinguish "no mutable handle exists"
from "a mutable handle exists but nobody tried it through the proxy."

**How to apply:** when reviewing a frozen-mapping state machine, check that
the dict literal is inline (no named handle) rather than just checking the
proxy raises `TypeError`. If a named handle is ever introduced, the decisive
test asserts no module-level name besides the public frozen mapping binds a
mutable object, not merely that writes through the public name fail. See
D-014's `StructurePlan.legs` shared-reference reasoning for the same hazard in
a different shape.

## AST-based "no forbidden import" tests need substring/prefix matching, not exact membership

`ast.Import` records dotted module names whole (`import datetime.timezone`
records `"datetime.timezone"`, not `"datetime"`), and `ast.ImportFrom` with a
relative import (`from . import time`) has `node.module is None` and is
silently skipped by a check that only looks at `node.module`. A forbidden-list
test using exact `in` membership passes on both. Use
`m == forbidden or m.startswith(forbidden + ".")` and also collect
`node.names` when `node.module` is falsy.

UNIT-033 round two fixed exactly this (verified: `import os.path as p`,
`from datetime import timezone`, and `from . import time` are all now caught).
But the fixed version still only walks `ast.Import` and `ast.ImportFrom`
nodes, so it is blind to dynamic import by call: `__import__("time")` and
`importlib.import_module("time")` evade it entirely, and neither is caught by
a companion "no forbidden call" check either, because that check (rightly)
only inspects `ast.Call` nodes whose `func` is a bare `ast.Name` matched
against a short builtin list (`open`, `print`, `input`, `eval`, `exec`);
`__import__` is a builtin but not in that list, and
`importlib.import_module(...)` has `func` as `ast.Attribute`, which the check
excludes by construction. Graded LOW in that review: it requires deliberately
adversarial code to exploit, not an accidental refactor, which is a different
threat model from the literal-hoist case above. Worth checking for on any
future AST-based "no clock, no I/O" test, but not worth blocking on by itself.

## A "no bare dict at module level" AST check needs to match construction shape, not just literal shape

The fix for the mutable-table-handle finding above (`_TABLE = {...};
LEGAL_TRANSITIONS = MappingProxyType(_TABLE)`) walks `tree.body` and raises on
any `ast.Assign`/`ast.AnnAssign` whose `.value` is `ast.Dict | ast.DictComp`.
Verified this catches the exact literal-hoist shape it was written for. It
does not catch `_TABLE = dict(...)` (value is `ast.Call`, not `ast.Dict`) or a
tuple-target assignment like `_TABLE, _X = {...}, {}` (value is `ast.Tuple`
wrapping two `ast.Dict` nodes, not an `ast.Dict` itself). Both would still bind
a mutable module-level handle to feed into `MappingProxyType(...)`. Graded LOW
in that review for the same reason as the import gap: requires an unusual,
deliberate construction shape rather than an accidental one. The general
principle from the original note still holds and is the more robust target:
check that no module-level name binds *any* mutable object, not that no
module-level name binds a dict *literal*.
