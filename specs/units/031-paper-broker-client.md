---
id: UNIT-031
title: Implement the paper broker client behind the merged protocols
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-006, UNIT-032, UNIT-010, UNIT-011, UNIT-012, UNIT-015, UNIT-017]
paths: src/alphaledger/broker/client.py, tests/execution/test_client.py
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

[NEEDS CLARIFICATION: C1, C2, C4, C7. C1 is structural and invalidates this unit's contract: the merged `PaperTransport` takes no HTTP method and `TransportResponse` carries no body, so this unit cannot perform a read or parse a response through it, and the feature spec forbids changing a merged unit. C2: the submission boundary requires an arm and does not require the risk approval, the durable attempt, the payload binding, the derived client order id, or the smoke test cap that `AGENTS.md` says the only order path must enforce. C4: reading the arm before submit is not atomic with disarm. Recorded 2026-09-01 from the Codex analysis pass in
`specs/features/001-autonomous-session/analysis-codex.md`, which found seven
CRITICAL and five HIGH findings that five earlier passes missed. A fix pass was
started and stopped before it completed, and its partial edits were discarded
rather than shipped half applied, so every finding below is open. Do not claim
this unit until it is resolved and this marker is removed.]

## Problem

Four Protocols are declared in merged code and none has an implementation:
`PaperTransport` in `broker/endpoint.py`, `BrokerOrderLookup` in
`execution/lifecycle.py`, `BrokerTruthSource` in `execution/reconcile.py`, and
`PositionSource` in `execution/killswitch.py`. Every unit that would use them
is tested against in-memory doubles, so nothing in this repository has ever
reached a broker.

## Source of truth

- `specs/features/001-autonomous-session/spec.md`, criteria 1, 2, 5, 10, 12,
  and the Clarifications entry ruling out `alpaca-py` for this path.
- `specs/features/001-autonomous-session/plan.md`, Package before bespoke.
- `.claude/rules/01-safety.md` bullets 1 and 4.
- `.claude/rules/30-execution.md` bullets 1, 2, and 5.

## Scope

In:

- A concrete `PaperTransport` over `httpx`, refusing redirects at run time.
- Implementations of `BrokerOrderLookup`, `BrokerTruthSource`, and
  `PositionSource`, parsing responses through UNIT-011's merged
  `parse_order`, `parse_activity`, and `parse_position`.
- Credentials read from the environment and never recorded anywhere.
- Reading the arm record at the call it authorises, per criterion 5.

Out:

- Deciding anything. This unit maps requests and responses and holds no state.
  Whether to submit is UNIT-013's and UNIT-034's.
- Parsing broker JSON into records. UNIT-011 owns that and is merged; calling
  it is in scope, reimplementing it is not.
- Retry policy on the order path. UNIT-012's `decide_submission` and
  `recover_submission` already own what happens after an ambiguous submit, and
  a retry above them would undo it.
- Any import of `alpaca.trading`, which carries a `paper: bool` resolving to
  the live host. See criterion 11 in the spec.

## Contract

`alphaledger.broker.client`.

The transport satisfies the merged `PaperTransport` Protocol exactly as
declared, including `follow_redirects: Literal[False]`. That typing constrains
callers and constrains nothing at run time, so the implementation must refuse a
redirect itself and be tested for it.

Every request asserts the paper endpoint through UNIT-010's merged
`assert_paper_endpoint` before it is sent, not once at construction.

The three read Protocols are satisfied by narrow methods that fetch and parse.
They perform no retry that could turn one broker fact into two.

Submission requires the value UNIT-032 produces from a live arm read, and the
read happens immediately before the call it authorises. Caching it for the
duration of an invocation is the failure criterion 5 forbids.

Credentials come from the environment by name and are attached to requests
only. No exception this module raises carries one, and no code path logs one.

## Acceptance criteria

- AC-1: a redirect response is refused at run time, without following it.
  Falsified by a stubbed server answering 3xx with a `Location` the client then
  requests. The Protocol's typing does not establish this; only this test does.
- AC-2: every request path calls `assert_paper_endpoint` before sending.
  Falsified by any request reaching a stub without the assertion having run.
- AC-3: a request to any host but the paper endpoint raises before a body is
  sent. Falsified by a body arriving anywhere else.
- AC-4: no exception raised by this module carries a credential, tested with a
  sentinel secret across every failure path the module can produce. Falsified
  by the sentinel appearing in any message, argument, or recorded traceback.
- AC-5: submission is impossible without the value UNIT-032 produces.
  Falsified by any reachable call that submits without one.
- AC-6: the arm is read immediately before the submitting call, not earlier.
  Falsified by an implementation that reads once and submits twice, proven by a
  test that disarms between two submissions and observes the second refused.
- AC-7: `parse_order`, `parse_activity`, and `parse_position` are called rather
  than reimplemented. Falsified by any JSON field access in this module that
  duplicates what those functions do.
- AC-8: no import of `alpaca.trading` and no live host string exist in this
  module. Falsified by either appearing.
- AC-9: no test reaches the network. Falsified by a suite that fails when
  offline.

## Test list

- success: a submit maps to the documented request shape and its response
  parses through `parse_order` into a `BrokerOrder`.
- success: the three read Protocols each return parsed records from a stubbed
  response.
- failure: a 3xx with a `Location` is refused and the location is never
  requested, asserted on the stub's recorded request list rather than on a flag
  the client sets.
- failure: a non paper host raises before any body is sent, asserted on the
  stub having received nothing.
- failure: every error path is exercised with a sentinel credential in the
  environment, and the sentinel appears in no message or traceback.
- failure: submitting without the arm value is impossible, attempted through
  every public path.
- restart: a client constructed fresh in a subprocess reaches the same endpoint
  and produces the same request bytes for the same inputs.
- restart: an arm that expires between two submissions causes the second to be
  refused, which is the cached read defect stated as a test.
- no-trade: a read that returns an empty order list is a normal result and
  raises nothing, because an account with no open orders is the ordinary case.

## Verification

```bash
uv run pytest tests/execution/test_client.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
