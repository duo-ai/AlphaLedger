---
id: UNIT-033
title: Model the session and arm state machine
lane: execution
state: in_review
owner: mazwy/claude
branch: feature/033-session-machine
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-012]
paths: src/alphaledger/execution/session.py, tests/execution/test_session.py
claimed_at: 2026-09-02T13:23:42Z
reviewed_by: execution-safety-reviewer
review_verdict: clear
reviewed_at: 2026-09-04T12:43:47Z
review_log: [conditional, clear]
---

## Delegated to mazwy

Assigned to `mazwy` on 2026-08-31 by the user, together with the other five
units of feature 001. These are execution lane paths rather than research ones,
so the roster in `AGENTS.md` is amended to record the exception rather than
leaving it to be inferred. `preferred_runtime` is `claude` because that is the
runtime the owner runs, and `scripts/dispatch.sh` refuses a Claude owner by
design, so these are claimed and worked in a session with worktree isolation
rather than dispatched.

## Problem

Design section 11 specifies a session and arm machine over seven states, and
UNIT-012's intake deliberately excluded it, saying the session states belong
with the orchestrator. Nothing implements it. Without it the orchestrator has
no vocabulary for what a session is doing and no way to refuse an illegal move.

## Source of truth

- `options-alpha-agent-design.md` section 11, the state diagram.
- `specs/features/001-autonomous-session/spec.md`, the Scope In entry on the
  state machine, which records two transitions the diagram omits and why they
  are required.
- `specs/units/012-order-state-machine.md`, for the shape to follow and for the
  boundary between the two machines.
- `.claude/rules/01-safety.md` bullet 4 and `.claude/rules/30-execution.md`
  bullet 8.

## Scope

In:

- The seven states: disarmed, ready, working, open, exiting, closed, halted.
- The transitions design section 11 names.
- Two the diagram omits and the rules require, recorded in the spec: a halt
  edge out of exiting, and a disarm edge from every non terminal state.
- Refusal of every transition outside that set, naming both states and the
  event.

Out:

- The per order machine, merged as UNIT-012. An order reaching a terminal state
  is an event this machine observes, never a state it enters.
- Deciding when to move. This module is a pure function of state and event;
  UNIT-034 decides which events occur.
- Persisting anything. UNIT-034 writes transitions to the ledger.

## Why two transitions are added

Recorded here so an implementer does not treat the diagram as complete and a
reviewer does not treat the addition as scope creep.

`Exiting` has exactly one outgoing edge in the diagram, to `Closed` on a
successful flatten. UNIT-017 is merged and reports a flatten that did not
complete, so the code can produce a fact the diagram gives the session nowhere
to put. `.claude/rules/01-safety.md` bullet 4 requires a fail closed halt on
uncertainty with no exception for exiting, and
`.claude/rules/30-execution.md` bullet 8 requires flatten failure to escalate
while keeping entry disabled. `Exiting -> Halted` is therefore required.

`Disarmed` appears only as the initial state, which read literally makes disarm
unreachable once running and contradicts section 11's own sentence that disarm
remains available. A disarm edge from every non terminal state is required.

## Contract

`alphaledger.execution.session`.

A `SessionState` enumeration of exactly seven members, a `SessionEvent`
enumeration of the events that drive the table, and a pure transition function
that returns the next state or raises naming both states and the event.

Follow UNIT-012's merged shape: a frozen mapping from (state, event) to state,
no clock, no I/O, no state retained between calls.

A predicate for whether a state permits a new entry. Halted and disarmed do
not; the others are decided by the table this unit writes down.

## Acceptance criteria

- AC-1: `SessionState` has exactly seven members, pinned by name. Falsified by
  an eighth, which would mean the machine grew a state the design does not
  have.
- AC-2: every transition in the table is accepted and every transition outside
  it raises, naming both states and the event. Falsified by a silent acceptance
  or by a message that names only one side.
- AC-3: `Exiting` transitions to `Halted`, proven by a test that names the
  flatten failure it stands for. Falsified by a raise, which is the behaviour
  the design diagram alone would produce.
- AC-4: every non terminal state transitions to `Disarmed` on a disarm event.
  Falsified by any state that refuses one.
- AC-5: `Halted` accepts no transition except disarm. Falsified by any other
  edge out of it, which would let a halted session resume without a human.
- AC-6: the module contains no per order state and no reference to
  `OrderState`'s members as session states. Falsified by either appearing,
  which is the confusion UNIT-012's intake exists to prevent.
- AC-7: the module reads no clock and performs no I/O. Falsified by any import
  of `datetime.now`, `time`, or anything under `alphaledger.broker`.

## Test list

- success: a full path from disarmed through ready, working, open, exiting, to
  closed, and back to ready.
- success: `Exiting` to `Halted` on a flatten that did not complete.
- success: disarm from each of the six non terminal states.
- failure: a transition outside the table raises and names both states and the
  event, parameterised across every illegal pair rather than one example.
- failure: an attempt to leave `Halted` by anything but disarm raises.
- failure: the enumeration has exactly seven members, listed by name, so an
  eighth cannot be added without a test failing.
- restart: the machine is pure, so the same state and event yield the same
  result in a subprocess. This is what lets UNIT-034 rebuild a session from the
  ledger and get the same answer.
- no-trade: a session that reaches `ready` and never leaves it is a legal path,
  and the entry predicate says so.

## Verification

```bash
uv run pytest tests/execution/test_session.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

### Implementation, 2026-09-02

The table has seventeen edges: the ten design section 11 draws, `Exiting ->
Halted`, and six disarm edges, one from every state that is not `Disarmed`
itself. Forty-nine (state, event) pairs exist and thirty-two are refused, and
the test sweeps all of them rather than sampling, so an edge added by accident
fails a test rather than being discovered by an orchestrator.

`SessionEvent` names each event for the state it attempts to enter, following
UNIT-012. That is what lets a refusal name both sides of a move, which AC-2
requires: with no target in the event there would be nothing to name but the
current state. The cost is real and is accepted rather than hidden. Four
distinct causes share the `HALTED` event, a health breach, a risk breach, a
kill switch, and a flatten that did not complete, because the machine's only
question is whether the move is legal and all four make the same move. Which
cause fired is a fact for the ledger, and UNIT-034 owns recording it. AC-3 is
tested by a case named for the flatten failure it stands for, so the
distinction is visible in the test suite even though it is absent from the
enumeration.

`permits_new_entry` is derived from the table rather than written as a second
list, `(state, SessionEvent.WORKING) in LEGAL_TRANSITIONS`. The intake allows
either, saying halted and disarmed must not permit entry and the rest are
decided by the table. A separate list could drift from the transitions, and the
direction it would drift in is the dangerous one: a stale list saying a halted
session may trade. A test pins the property rather than the current answer, so
if a later unit adds an edge into `working` the predicate follows it instead of
being a stale copy.

AC-6 and AC-7 are checked against the module's syntax tree, not by grepping its
text. The first attempt grepped, and it failed on this module's own docstring
explaining why the per-order machine is a different scope. That is not a near
miss worth ignoring: the same weakness runs the other way, since a grep would
also pass on an import smuggled in under an alias. The tree sees imports,
names, and calls, and nothing else.

Five mutations were injected and reverted, and each turned a test red, in every
case including the test named for that behaviour: dropping the `Exiting ->
Halted` edge, dropping the only edge out of `Halted`, adding a `Halted ->
Ready` edge that would let a halted session resume with no human, replacing the
derived entry predicate with a hand-written state list, and adding an eighth
state.

### Round one, 2026-09-02, `execution-safety-reviewer`, verdict `conditional`

Four findings. Three were test-soundness defects, all real, all fixed. The
fourth is a specification question and is surfaced rather than answered here.

Two of the three fixed findings are holes in the AST checks that replaced the
first, grep-based versions of the AC-6 and AC-7 tests. `ast.Import` records a
dotted name whole, so `import datetime.timezone` is the single string
`"datetime.timezone"` and an equality test against `"datetime"` misses it;
`ast.ImportFrom` carries `module is None` for a relative import, so
`from . import time` was skipped entirely and neither the module nor the name
was recorded. The checks now test the prefix and record `alias.name` in both
node shapes. Neither hole was exploited by the four-line import block in this
module, so both are test-soundness rather than live violations, but the second
version of a test being weaker than it reads is exactly the pattern the first
version was rewritten to escape.

The third: the thirty-two case illegal-pair sweep asserted that each of three
names appeared in the refusal message, and that was weaker than it read.
`SessionEvent` and `SessionState` share string values by construction, so the
target's name and the event's name are always the same string, and a
`transition` that dropped `to '{target}'` from its message entirely would have
satisfied all three membership checks in all thirty-two cases. Only the single
hard-coded message test would have caught it, so AC-2 was pinned by one example
while appearing to be pinned by thirty-two. The sweep now asserts the whole
message.

A fourth, `MappingProxyType` is a view rather than a copy, so the dict literal
has to stay inline. Nothing binds a mutable handle today, and the existing
immutability test would keep passing if a later refactor hoisted the literal to
a named variable, while `session._TABLE[...] = ...` mutated the machine at run
time, including adding an edge out of `halted`. A new test walks the module's
top-level statements and fails on any module-level name bound to a bare dict.

The finding not fixed, `Closed -> Halted`. The reviewer graded it HIGH: the
reasoning that authorised `Exiting -> Halted` is not specific to exiting, so a
kill switch firing while a session sits in `closed` has nowhere to go but a
refusal, and `closed` is two events from permitting an entry. The
counter-argument is that `closed` holds no position and no working order, so
declining to move on to `ready` is already the fail-closed response
`.claude/rules/01-safety.md` bullet 4 asks for, and a halt is not the only safe
answer there. Both readings are defensible, which is precisely why this unit
does not choose between them: adding the edge would be a third deviation from a
cited design source where this intake's Scope authorises exactly two, and
`AGENTS.md` requires surfacing a conflict rather than resolving it, and
specifically rather than resolving it silently. The decision belongs to whoever
owns `specs/features/001-autonomous-session/spec.md`, which is where the first
two deviations are recorded and where a third would have to be.

The reviewer also showed the code comment above the halt edges was false as
written: it said "every state that can still be holding or placing risk", and
`ready` has a halt edge while holding nothing. That is fixed, and the comment
now records the `closed` question and warns UNIT-034 not to route a halt
through `closed -> ready -> halted`, because `permits_new_entry` is true in the
state that path passes through.

Recorded because it bears on how much this round's verdict is worth:
`execution-safety-reviewer` has no Bash tool, so it ran no command. It said so
plainly instead of implying otherwise, and it hand-counted the parametrised
cases to 59 against the claimed 59. Its four findings were all derived
statically and three were confirmed real. The implementer ran the gate and the
mutations; the reviewer verified neither, and no reviewer under this agent
definition can.
