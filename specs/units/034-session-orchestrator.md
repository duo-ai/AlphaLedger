---
id: UNIT-034
title: Run one scheduled session invocation start to finish
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-031, UNIT-032, UNIT-033, UNIT-004, UNIT-005, UNIT-011, UNIT-012, UNIT-013, UNIT-014, UNIT-015, UNIT-016, UNIT-017, UNIT-018, UNIT-019]
paths: src/alphaledger/execution/orchestrator.py, tests/execution/test_orchestrator.py
---

## Delegated to mazwy

Assigned to `mazwy` on 2026-08-31 by the user, together with the other five
units of feature 001. These are execution lane paths rather than research ones,
so the roster in `AGENTS.md` is amended to record the exception rather than
leaving it to be inferred. `preferred_runtime` is `claude` because that is the
runtime the owner runs, and `scripts/dispatch.sh` refuses a Claude owner by
design, so these are claimed and worked in a session with worktree isolation
rather than dispatched.

## Blocked

[NEEDS CLARIFICATION: C1, C2, C5, C6. C1 and C2 reach this unit through UNIT-031, whose contract is impossible as written. C5: AC-7 says this module holds no trading rule of its own and is falsified only by arithmetic or a threshold comparison, so a structure or exit selection added with neither would pass while breaking the invariant it claims. C6: no unit records operator driven arm and disarm transitions. Recorded 2026-09-01 from the Codex analysis pass in
`specs/features/001-autonomous-session/analysis-codex.md`, which found seven
CRITICAL and five HIGH findings that five earlier passes missed. A fix pass was
started and stopped before it completed, and its partial edits were discarded
rather than shipped half applied, so every finding below is open. Do not claim
this unit until it is resolved and this marker is removed.]

## Problem

Every component of a trading decision is merged and nothing calls them in
order. There is no path from a scan to a submitted order and back, so the
project's central claim, that these parts compose into an agent that trades
safely, has never been exercised.

## Source of truth

- `specs/features/001-autonomous-session/spec.md`, criteria 2, 4b, 6, 7, 8, 9,
  and 14, and the Clarifications entry on scheduled invocations.
- `specs/features/001-autonomous-session/plan.md`, the criterion table.
- `.claude/rules/30-execution.md` bullets 5 and 6.
- `options-alpha-agent-design.md` sections 11 and 15.

## Scope

In:

- One invocation, start to finish: verify the configuration hash against the
  arm, reconcile against broker truth, rebuild session state from the ledger,
  decide, act, record every transition, exit.
- Refusing new entries while any order state is unknown, naming which order.
- Recording every session transition, including entry into halted and every
  no-trade.

Out:

- Trading logic of any kind. Sizing is UNIT-013's, structure selection
  UNIT-014's, rung prices UNIT-019's, the ladder UNIT-018's, reconciliation
  UNIT-015's, exits and flatten UNIT-017's, the order lifecycle UNIT-012's. If
  this module grows a rule of its own, the decomposition is wrong.
- Holding the arm across the invocation. It reads the arm to compare hashes;
  the arm read that authorises a submission belongs to UNIT-031, per
  criterion 5.
- The human commands. UNIT-035 owns arm, disarm, halt, and flatten as
  invocations a person starts.
- Scheduling itself. What starts an invocation is an operating concern, not
  this module's.

## The shape this unit is, and is not

It is a function that runs once and returns. It holds no state between
invocations and carries nothing in memory across one, because there is no
process between them.

Reconstruction is therefore the ordinary path and not a recovery path. That is
the reason the invocation model was chosen: in a long lived process the restart
path runs only after a crash and is the least exercised code in the system at
the moment it matters most. Here it runs on every scan.

## Contract

`alphaledger.execution.orchestrator`.

One entry point that takes the collaborators it needs as arguments, so every
test supplies doubles and no test reaches a network. It returns a record of
what the invocation did, including the case where it did nothing.

Order of operations, and it is load bearing rather than stylistic:

1. Read the arm. If absent, record and stop.
2. Recompute the frozen configuration hash and compare it to the arm's. On
   mismatch, disarm and stop. This is criterion 4b and design section 15.
3. Reconcile through UNIT-015 against broker truth.
4. Rebuild session state from the ledger.
5. If anything is unexplained or any order state is unknown, refuse new entries
   and record why.
6. Otherwise decide, act through the merged units, and record every transition.

Every step that changes the session state writes it before the next step reads
it. Under this model the ledger is the source of session truth rather than a
record of it, so a transition that is not written did not happen as far as the
next invocation can tell.

## Acceptance criteria

- AC-1: an invocation with no arm records the fact and submits nothing.
  Falsified by any submission, and by an invocation that stops silently.
- AC-2: a configuration hash differing from the arm's disarms and stops.
  Falsified by an invocation that trades under a configuration differing from
  the armed one.
- AC-3: every session transition reaches the ledger before the invocation
  exits, including entry into halted and every no-trade. Falsified by a
  transition observable in the returned record and absent from the ledger.
- AC-4: an unknown order state refuses new entries and names the order and the
  reason. Falsified by an entry accepted while an unresolved submission exists,
  and by a refusal that does not say which order caused it.
- AC-5: a process killed between any two steps leaves the next invocation
  agreeing with broker truth, or refusing and naming the fact it could not
  establish. Falsified by a reconstruction that silently differs from the
  broker in any order or position.
- AC-6: no second intent is submitted for a decision whose first submit was
  interrupted, proven over UNIT-012's merged primitives. Falsified by two
  broker orders carrying one derived client order id.
- AC-7: the module contains no sizing, pricing, structure selection, or exit
  rule of its own. Falsified by any arithmetic on money or any threshold
  comparison that is not delegated.
- AC-8: no ledger entry this module writes carries a credential. Falsified by a
  sentinel secret appearing in any entry.
- AC-9: an invocation that decides not to trade produces the same evidence
  trail as one that does. Falsified by a no-trade path that records less.

## Test list

- success: a full invocation from arm through decision to a recorded submission
  and its reconciliation.
- success: a no-trade invocation records a complete trail, asserted field by
  field against the trading case rather than by counting entries.
- failure: no arm, expired arm, and mismatched configuration hash each stop and
  record, tested separately because they are three different refusals.
- failure: an unresolved submission blocks a new entry and the refusal names
  the order.
- failure: an unexplained broker position blocks entries, using UNIT-015's
  merged report rather than a local check.
- restart: an invocation interrupted after each step in turn is followed by a
  fresh invocation that agrees with broker truth, parameterised over the steps
  rather than testing one.
- restart: two invocations over identical inputs produce identical records, so
  reconstruction is deterministic.
- no-trade: an invocation in `ready` with no admissible candidate records the
  reason and leaves the session in `ready`.

## Verification

```bash
uv run pytest tests/execution/test_orchestrator.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
