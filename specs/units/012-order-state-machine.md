---
id: UNIT-012
title: Implement the order state machine and idempotent client order ids
lane: execution
state: claimed
owner: pablo/codex
branch: feature/012-order-state-machine
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-011]
paths: src/alphaledger/execution/lifecycle.py, tests/execution/test_lifecycle.py
claimed_at: 2026-08-29T10:17:12Z
reviewed_by: execution-safety-reviewer
review_verdict: block
reviewed_at: 2026-08-29T10:39:27Z
review_log: [block]
---

## Problem

An order submitted without a stable identity cannot be recovered. If a submit
times out and the system cannot ask the broker "did you already take this
intent", the only options are to resubmit, which risks a duplicate position, or
to do nothing, which risks an unmanaged one. Both are unacceptable, and the
difference between them is an identifier derived before the request is sent.

## Source of truth

- `.claude/rules/30-execution.md`, bullets 3, 4, 5 and 6.
- `options-alpha-agent-design.md` section 11, entry steps 3 and 5.
- `options-alpha-agent-design.md` section 15, the rows for unknown submission
  result and for a partial or working order beyond budget.
- `hackathon-build-plan.md` section 4, the evening test list.

## Two different machines

`.claude/rules/30-execution.md` bullet 4 names eleven states: proposed,
rejected, submitted, working, partial, filled, cancel-pending, canceled,
expired, closing, reconciled. That is a **per-order** machine and it is what
this unit implements.

Design section 11 shows a different diagram: disarmed, ready, working, open,
exiting, closed, halted. That is a **session and arm** machine covering the
whole trading day. The two are different scopes, not a conflict. Do not
reconcile them into a single machine, and do not implement the session states
here; they belong with the orchestrator.

## Scope

In:

- Deterministic `client_order_id` derived from `(plan_id, quantity, limit_price)`,
  which are all fixed before a risk approval exists. The same values produce the
  identical string in a later process. One stable id per intent, per rule
  bullet 3. See "The identifier ordering" below for why the approval is not an
  input.
- The eleven-state enum and the legal transition table given below. An illegal
  transition raises rather than being recorded.
- Broker-terminal detection, and the single lifecycle-terminal state.
- Ambiguity handling. A submit that times out, returns nothing, or returns an
  unparseable result leaves the order with no known state, never `rejected`.
  Resolution is a query by client order id. There is never a second submit.
- A duplicate-invocation guard: submitting the same intent twice yields one
  broker intent, not two.
- Fail-closed behaviour on unknown order state, per rule bullet 6.

Out:

- The scheduled reconcile loop across orders, activities and positions, and
  orphan-position recovery (UNIT-015). This unit owns query-by-client-id as a
  primitive and the unknown-fails-closed rule. It must not grow into UNIT-015.
- Choosing or stepping a limit price. `specs/000-INTAKE.md` assigns
  UNIT-013 to the risk approval token, so an earlier draft of this line
  named the wrong unit; the ladder has no unit assigned yet. This unit may
  model `cancel_pending`, but it does not decide prices.
- Building or parsing the payload (UNIT-011).
- Endpoint assertion and transport (UNIT-010). This unit performs no I/O. The
  broker is reached only through the lookup protocol below, which a test
  satisfies with an in-memory object.

## The identifier ordering

The id is derived from `(plan_id, quantity, limit_price)`. It is not derived
from `approval_id`, and that is a correction to an earlier draft of this intake
rather than a matter of taste.

`build_mleg_order` places `client_order_id` inside the payload, and
`order_payload_hash` hashes that payload, and `RiskApproval.order_payload_hash`
binds to that hash. Deriving the id from `approval_id` would therefore require
the approval to exist before the id, and the id to exist before the payload the
approval is bound to. That is a cycle and it cannot be implemented.

The ordering is:

    plan_id, quantity, limit_price
        -> client_order_id
        -> build_mleg_order, whose payload contains the id
        -> order_payload_hash
        -> RiskApproval, bound to the exact payload that will be submitted

Two sources disagreed here and the conflict was surfaced rather than resolved
by preference. `options-alpha-agent-design.md` section 11 step 3 and
`orchestrator-system-prompt.md` both describe approval first, with the adapter
owning the id and the caller observing it only after submission. UNIT-011,
merged and reviewed clear, requires the id to be inside the hashed payload so
that an approval cannot authorise a changed quantity or price. The second was
chosen. This is recorded as D-023, which UNIT-013, UNIT-014, and UNIT-015
inherit.

Obligation this places on the caller: `plan_id` must be unique per plan
instance. If two distinct decisions could ever carry the same `plan_id` at the
same quantity and price, they would derive the same id and the second would be
silently collapsed into the first. AC-8 pins this as a stated precondition, so
that a later change to plan identity cannot quietly break idempotency.

## The transition table

`OrderState` has exactly the eleven members rule bullet 4 names, and no more:
`proposed`, `rejected`, `submitted`, `working`, `partial`, `filled`,
`cancel_pending`, `canceled`, `expired`, `closing`, `reconciled`.

Legal transitions, and nothing else:

| From | To |
|---|---|
| `proposed` | `submitted`, `rejected` |
| `submitted` | `working`, `partial`, `filled`, `rejected`, `canceled`, `expired` |
| `working` | `partial`, `filled`, `cancel_pending`, `canceled`, `expired` |
| `partial` | `filled`, `cancel_pending`, `canceled`, `expired` |
| `cancel_pending` | `canceled`, `partial`, `filled` |
| `filled` | `closing`, `reconciled` |
| `rejected` | `reconciled` |
| `canceled` | `reconciled` |
| `expired` | `reconciled` |
| `closing` | `reconciled` |
| `reconciled` | nothing |

`cancel_pending` transitions to `filled` or `partial` because a cancel can lose
the race against a fill. A machine that forbade it would raise on a sequence the
broker can really produce, and a raise is not a safe response to broker truth.

Two different notions of terminal, and they are not the same set. This corrects
an earlier draft that named one set and made two states unreachable.

- Broker-terminal: `filled`, `rejected`, `canceled`, `expired`. The broker will
  send no further update about the order. These still transition, to `closing`
  or `reconciled`, because exiting a position and reconciling it both happen
  after the broker is done.
- Lifecycle-terminal: `reconciled` alone. It has no successor, and a transition
  out of it raises.

## Ambiguity is the absence of a state, not a twelfth state

An ambiguous submit does not produce an order state. It produces the absence of
one. `unknown` is therefore not a member of `OrderState`, and adding it would be
a defect: a twelfth member could be passed to `transition` and asked whether it
is terminal, which are questions that have no answer for an order whose state
nobody knows.

It is represented as `None` where a state is expected, and the fail-closed rule
in bullet 6 is a predicate over `OrderState | None`.

## Contract

`alphaledger.execution.lifecycle`, importing from `alphaledger.domain` and
`alphaledger.execution.orders`. `alphaledger/execution/__init__.py` carries a
docstring and no re-exports; leave it that way, so this unit stays inside its
declared globs.

```python
def client_order_id(plan_id: str, quantity: int, limit_price: Decimal) -> str: ...

class OrderState(StrEnum): ...        # exactly the eleven states above
class OrderEvent(StrEnum): ...        # the events that drive the table above

def transition(current: OrderState, event: OrderEvent) -> OrderState: ...
def is_broker_terminal(state: OrderState) -> bool: ...
def is_lifecycle_terminal(state: OrderState) -> bool: ...
def blocks_new_entries(state: OrderState | None) -> bool: ...

class BrokerOrderLookup(Protocol):
    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None: ...

def resolve_ambiguous_submit(
    lookup: BrokerOrderLookup, client_order_id: str
) -> OrderState | None: ...
```

`client_order_id` is pure: no clock, no randomness, no counter. Anything that
varies between processes defeats the recovery it exists to enable.

`BrokerOrder` comes from `alphaledger.execution.orders`, already merged. Its
`status` is a `BrokerOrderStatus`, so mapping broker status to `OrderState` is
this unit's work and belongs in this module.

The duplicate-invocation guard is a decision function, not a submit path, since
this unit performs no I/O. It must distinguish three outcomes and the
implementer may name the return type: no order exists so the caller may submit;
an order already exists so the caller adopts it and does not submit; broker
truth is unavailable so the caller fails closed and submits nothing.

## Acceptance criteria

- AC-1: the same `(plan_id, quantity, limit_price)` yields the identical
  `client_order_id` in a separate process, and different inputs never collide.
- AC-2: every transition in the table above is accepted and every transition
  outside it raises, naming both states and the event.
- AC-3: `reconciled` accepts no further transition. A broker-terminal state
  still reaches `closing` or `reconciled`, and a test proves both are reachable,
  because a machine in which they are not is incoherent.
- AC-4: an ambiguous submit yields no state, triggers a query by client order
  id, and no code path resubmits after it. The entry point a restarting caller
  uses cannot return a decision to submit, whatever it is passed. This is a
  property of the function's shape, not of the caller's diligence.
- AC-5: invoking the same intent twice results in one broker intent. The second
  invocation recognises the first by its id rather than creating a new one. The
  evidence that a submit was already attempted is a value a caller can only hold
  by having recorded the attempt, never a bare `bool` that is false by default,
  by omission, or after a crash. A caller that cannot produce it is refused, not
  permitted to submit.
- AC-6: `blocks_new_entries` is true for `None` and for every state in which an
  entry would be unsafe, and a test states which states those are rather than
  asserting on the implementation's own list.
- AC-7: the module contains no session or arm states, and `OrderState` has
  exactly eleven members, pinned by name.
- AC-8: `client_order_id` takes no approval, no clock, and no randomness, and
  its docstring states the caller's obligation that `plan_id` is unique per plan
  instance.
- AC-9: broker truth beating local state is exercised by passing a disagreeing
  local state into the code under test and observing the broker's answer win. A
  local variable that is constructed in the test and never passed in does not
  satisfy this, because the assertion holds whether or not the behaviour exists.

## Test list

- success: a full path from proposed through submitted, working, partial,
  filled, closing, to reconciled.
- success: the same inputs produce the same id across two processes.
- success: a cancel that loses the race, cancel_pending to filled, is accepted.
- failure: an illegal transition raises and names both states and the event.
- failure: a transition out of reconciled raises.
- failure: an ambiguous submit yields no state, a query by id follows, and no
  second submit occurs. Assert on the absence of the second submit.
- failure: two invocations of one intent produce one broker intent.
- failure: the enum has exactly eleven members, listed by name, so a twelfth
  cannot be added without a test failing.
- restart: reconstructing state from a recorded id and the broker's answer
  yields the same state as before the restart, and the broker's answer wins
  over local state.
- restart: a subprocess derives the identical id from the same inputs, so a
  crash between derivation and submission is recoverable.
- no-trade: an unknown order state blocks a new entry, and the reason is
  recorded rather than the entry silently proceeding.

## Verification

```bash
uv run pytest tests/execution/test_lifecycle.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## The price ladder, still deferred

Design section 11 step 4 describes a bounded price ladder that moves the limit.
Whether a ladder step could reuse an id through a replace depends on Alpaca's
replace semantics, which `project-state/STATUS.md` lists as unverified while G0
is open. Do not guess.

The ordering decided above makes the interim answer fall out rather than needing
a separate mechanism. Because `limit_price` is an input to the derivation, a
ladder step at a new price yields a new deterministic id by construction, which
is exactly the fail-closed default of cancel and then resubmit under a new
deterministic id. A retry at the same price yields the same id, which is what
makes an ambiguous submit safe to resolve. UNIT-013 inherits both properties.

## Handoff notes

- 2026-08-29 code review round one, `execution-safety-reviewer`, verdict block.
  One P1 finding and one unsound test, both confirmed against the code by the
  session before being recorded here.

  Finding 1, `lifecycle.py` `decide_submission`. The safety property is gated on
  a caller-supplied `submission_attempted: bool`. When the broker lookup returns
  `None` and that flag is false, the function returns `SUBMIT`. A process that
  crashes after the request leaves the machine but before the caller durably
  records the attempt restarts into exactly that branch: the broker has not yet
  made the order visible, the flag is false again, and a second intent is
  submitted. AC-5 does not hold across a crash, and rule bullet 3's "never
  create a second intent implicitly" is broken by the shape of the argument.

  This repository has rejected this shape once already. UNIT-010's load-bearing
  clause is that no `paper: bool` exists anywhere, because a boolean can be set
  to false, and D-021 records that as the reason spec-kit's what-versus-how
  split was refused here. A safety property carried by a bare bool is the same
  defect wearing a different name.

  The correction stays inside the declared globs and adds no I/O. Provide a
  recovery entry point that structurally cannot return `SUBMIT`, so a caller
  resuming after a restart can only adopt or block. Replace the bare bool with a
  value a caller can only hold by having recorded the attempt; this unit defines
  that type and refuses without it, and the caller still owns persistence. State
  the obligation in the docstring so the submission adapter inherits it
  knowingly rather than by reading this file.

  Finding 2, `test_restart_rebuilds_the_same_state_and_broker_truth_overrides_local_state`.
  The test does not test its name. `stale_local_state` is assigned
  `OrderState.WORKING` and never passed to anything, and the assertion
  `after_restart is not stale_local_state` holds because the answer is `FILLED`.
  Nothing in the test exercises local state losing to broker truth, and it would
  pass unchanged against a function that had no notion of local state, which is
  what `resolve_ambiguous_submit` currently is. AC-9 above now states what the
  test has to do instead, which requires a path that actually accepts a recorded
  local state and refuses to prefer it.

  Finding 3, minor, not blocking on its own. The transition table is hand rolled.
  `AGENTS.md` asks that a package which already solves a problem be named and
  ruled in or out before bespoke code is written, and `transitions` and
  `python-statemachine` both solve state machines. A fixed table of twenty six
  entries is very likely the right answer here, but the reasoning has to be
  written down rather than skipped. Record it in these notes.

  Deliberately not carried into this unit. The review's closing paragraph lists
  a next-gate matrix covering host assertion, approval and hash binding, sizing,
  stale data, exits and flattening, and ledger completeness. None of those is an
  acceptance criterion of UNIT-012 and none is actionable inside its two
  declared paths. They belong to UNIT-010, UNIT-013 onward, and UNIT-016. Per
  D-022 they carry no severity here and must not be implemented in this unit.
