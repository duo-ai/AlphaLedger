---
id: UNIT-033
title: Model the session and arm state machine
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-012]
paths: src/alphaledger/execution/session.py, tests/execution/test_session.py
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
