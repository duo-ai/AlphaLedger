---
id: UNIT-012
title: Implement the order state machine and idempotent client order ids
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-011]
paths: src/alphaledger/execution/lifecycle.py, tests/execution/test_lifecycle.py
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

- Deterministic `client_order_id` derived from the intent, specifically
  `(plan_id, approval_id, intent)`. The same intent produces the identical
  string in a later process. One stable id per intent, per rule bullet 3.
- The eleven-state enum and the legal transition table. An illegal transition
  raises rather than being recorded.
- Terminal state detection: filled, canceled, expired, rejected.
- Ambiguity handling. A submit that times out, returns nothing, or returns an
  unparseable result is `unknown`, never `rejected`. Resolution is a query by
  client order id. There is never a second submit.
- A duplicate-invocation guard: submitting the same intent twice yields one
  broker intent, not two.
- Fail-closed behaviour on unknown order state, per rule bullet 6.

Out:

- The scheduled reconcile loop across orders, activities and positions, and
  orphan-position recovery (UNIT-015). This unit owns query-by-client-id as a
  primitive and the unknown-fails-closed rule. It must not grow into UNIT-015.
- Choosing or stepping a limit price (UNIT-013). This unit may model
  `cancel-pending`, but it does not decide prices.
- Building or parsing the payload (UNIT-011).
- Endpoint assertion and transport (UNIT-010).

## Contract

`alphaledger.execution.lifecycle`, importing from `alphaledger.domain` and
`alphaledger.execution.orders`.

```python
def client_order_id(plan_id: str, approval_id: str, intent: Intent) -> str: ...

class OrderState(StrEnum): ...        # the eleven states
def transition(current: OrderState, event: OrderEvent) -> OrderState: ...
def is_terminal(state: OrderState) -> bool: ...
```

`client_order_id` is pure: no clock, no randomness, no counter. Anything that
varies between processes defeats the recovery it exists to enable.

## Acceptance criteria

- AC-1: the same intent yields the identical `client_order_id` in a separate
  process, and two different intents never collide.
- AC-2: every transition in the table is accepted and every transition outside
  it raises, naming both states.
- AC-3: a terminal state accepts no further transition.
- AC-4: an ambiguous submit result becomes `unknown` and triggers a query by
  client order id. No code path resubmits after an ambiguous result.
- AC-5: invoking the same intent twice results in one broker intent. The second
  invocation recognises the first by its id rather than creating a new one.
- AC-6: an `unknown` state blocks new entries rather than being treated as an
  absence of an order.
- AC-7: the module contains no session or arm states.

## Test list

- success: a full path from proposed through submitted, working, partial,
  filled, to reconciled.
- success: the same intent produces the same id across two processes.
- failure: an illegal transition raises and names both states.
- failure: a transition out of a terminal state raises.
- failure: an ambiguous submit is recorded as unknown, a query by id follows,
  and no second submit occurs. Assert on the absence of the second submit.
- failure: two invocations of one intent produce one broker intent.
- restart: reconstructing state from a recorded id and the broker's answer
  yields the same state as before the restart, and the broker's answer wins
  over local state.
- restart: a subprocess derives the identical id from the same intent, so a
  crash between derivation and submission is recoverable.
- no-trade: an unknown order state blocks a new entry, and the reason is
  recorded rather than the entry silently proceeding.

## Verification

```bash
uv run pytest tests/execution/test_lifecycle.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Open question to settle, not to guess

Rule bullet 3 requires one stable id per intent and forbids implicitly creating
a second. Design section 11 step 4 describes a bounded price ladder that moves
the limit. Whether a ladder step reuses the id through a replace, or derives a
deterministic child id after a cancel, depends on Alpaca's replace semantics.
`project-state/STATUS.md` lists current MLeg behaviour as unverified while G0 is
open.

Do not guess. Until the Day-0 schema smoke test settles it, implement the
fail-closed default: cancel, then submit a new deterministic child id derived
from the parent. Record the choice in the handoff notes so UNIT-013 inherits it
knowingly.

## Handoff notes
