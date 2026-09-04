---
id: UNIT-032
title: Hold the durable time limited arm record
lane: execution
state: claimed
owner: mazwy/claude
branch: feature/032-arm-record
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-004, UNIT-005, UNIT-016]
paths: src/alphaledger/execution/arm.py, tests/execution/test_arm.py, config/risk.toml, src/alphaledger/config/__init__.py, tests/config/test_config.py
claimed_at: 2026-09-04T13:04:38Z
---

## Delegated to mazwy

Assigned to `mazwy` on 2026-08-31 by the user, together with the other five
units of feature 001. These are execution lane paths rather than research ones,
so the roster in `AGENTS.md` is amended to record the exception rather than
leaving it to be inferred. `preferred_runtime` is `claude` because that is the
runtime the owner runs, and `scripts/dispatch.sh` refuses a Claude owner by
design, so these are claimed and worked in a session with worktree isolation
rather than dispatched.

## C3, C4 and C6, resolved 2026-09-04

C3 was correct and the intake was wrong: it asserted UNIT-005 had committed a
maximum arm lifetime. UNIT-005 committed three values, `max_snapshot_age`,
`daily_loss_stop_fraction`, and `peak_to_valley_fraction`, and none is an arm
lifetime. No such key exists in `config/risk.toml` or in `RiskConfig`, verified
rather than assumed.

Resolved by this unit committing it, which required widening its declared path
globs onto `config/risk.toml`, `src/alphaledger/config/__init__.py`, and the
config test. That bends D-010, and the bend is recorded here rather than taken
quietly. It is safe only under the condition D-027 named for the same bend:
this must be the only in-flight unit holding those paths, and `coord.py` refuses
a claim that overlaps, so the condition is enforced mechanically rather than
remembered. The alternative considered and rejected was a seventh prerequisite
unit owning one config key, which is real ceremony for a single frozen number
that nothing else can sensibly own.

The value is a declared default, not a selected one, exactly like the three
UNIT-005 committed. It is committed so it enters `risk_config_hash`, because
D-017's whole point is that a limit passed as a bare argument cannot be proven
after the fact, and an arm that expired cannot be audited if nothing records
how long it was meant to last.

C4 is closed by making the arm a lease rather than a value, and this unit owns
both sides of the window. The finding showed a real race that "read immediately
before the send" cannot close: a submit that pauses after the read and before
the transport call still sends after disarm returned success. So this unit
exposes an `ArmLease` acquired for the duration of a submit critical section,
and `disarm` does not return until every outstanding lease is released or
conservatively reconciled. Emergency halt and flatten take a separate path that
the lease cannot starve, because a halt that had to wait for an in-flight
submit would be a halt that does not halt. The controlled-barrier test that
pauses between the acquire and the send lives here, since a test that disarms
between two completed submissions cannot exercise the window at all.

C6 is closed by giving the ledger write to this unit rather than to UNIT-034.
The finding was that an operator can arm or disarm with no scheduled scan
following, so the durable arm store changes while the append-only ledger holds
no corresponding transition, and the two durable truths disagree. Both writes
happen here, and the ordering is fixed and load bearing: the ledger entry is
appended first, then the arm store changes. A crash between them leaves a
ledger saying a session armed and an arm store saying it did not, which is the
fail-closed direction, because no arm means nothing can be submitted. The
opposite ordering would leave a live arm no audit trail explains, which is the
one outcome this project cannot accept.

## Problem

`config/risk.toml` commits `require_human_paper_arm` and no code reads it.
`.claude/rules/30-execution.md` bullet 2 requires submission to need a time
limited human arm state, and nothing in the merged tree holds one, so the arm
is a stated intention rather than a fact anything can check.

The orchestrator runs as scheduled invocations, each of which exits, so the arm
outlives every process that reads it. It has to be durable or it does not
exist.

## Source of truth

- `specs/features/001-autonomous-session/spec.md`, criteria 3, 4, and 5, and
  the Clarifications entry on the two step arm.
- `.claude/rules/30-execution.md` bullet 2.
- `options-alpha-agent-design.md` section 11, the arm paragraph and the
  session diagram.
- `project-state/DECISIONS.md`, D-017 for why the lifetime is committed rather
  than invented.

## Scope

In:

- The arm record: what it holds, how it is written, how it is read, and when it
  is expired.
- Binding to the frozen configuration hash `alphaledger.config.config_hash`
  produces.
- Expiry against a caller supplied instant, using the maximum lifetime
  UNIT-005 committed to `config/risk.toml`.
- The value a submit path must hold in order to submit, so that submitting
  without a live arm is a type error rather than a missed check.

Out:

- The human interface that creates one. UNIT-035 owns the two step arm, disarm,
  and the display of the hash.
- Reading it at the moment of submission. UNIT-031 does that, per criterion 5,
  because only the unit making the call can control when the read happens.
- Deciding to trade. This unit answers whether an arm is live and nothing else.

## Contract

`alphaledger.execution.arm`.

The record carries at least the configuration hash it binds, the instant it was
created, the instant it expires, and an identifier for the operator action that
created it. It is frozen once written.

Reading returns either a live arm or an explicit absence. An expired arm reads
as absent, not as an arm with a flag, because a caller that can see an expired
arm can use one.

The value a submit path holds is producible only by a successful read. Follow
the shape UNIT-012 already uses for `RecordedSubmissionAttempt`, where the
caller cannot construct the evidence itself. That is criterion 3, and an `if`
guard is not it.

Durability: the store must survive process exit, and the record must be
readable by a process that did not write it.

Storage, decided on 2026-08-31 rather than left open. The arm lives in its own
small store, not as an entry in UNIT-016's ledger.

The reason is the access pattern. The arm is read on every submission and
written twice in a session. UNIT-016 is append only, so answering whether the
system is armed would mean replaying a log to find the latest entry, which puts
a frequent read through a shape built for a different job. Disarm would also
become a superseding entry rather than a removal, so every reader would carry
the rule that the last entry wins, and a reader that forgot it would authorise
a submission against a revoked arm.

The ledger still records that arming and disarming happened, because those are
decisions and design section 13 wants them. What it does not hold is the answer
to whether an arm is live now.

The cost accepted: a second durable thing to get right. It is far simpler than
the ledger, holding one record rather than a history, and D-015's reasoning
about refusing to open a corrupt store applies here too and should be followed
rather than reinvented.

## Acceptance criteria

- AC-1: a written arm is readable by a separate process, and equal in every
  field. Falsified by any field that differs or by a read that finds nothing.
- AC-2: an arm past its expiry reads as absent. Falsified by any read that
  returns an expired arm in any form a caller could act on, tested strictly
  before, exactly at, and strictly after the expiry instant.
- AC-3: the value a submit path requires cannot be constructed except by a
  successful read. Falsified by any public constructor, factory, or dataclass
  call that produces one without reading a live arm.
- AC-4: the arm binds the configuration hash present when it was created, and
  exposes it for comparison. Falsified by an arm that does not record the hash,
  which would make UNIT-034's per invocation recheck impossible.
- AC-5: the maximum lifetime is read from the committed configuration, not
  from a constant in this module. Falsified by any literal duration in the
  source, per D-017.
- AC-6: disarm makes the arm read as absent immediately, from a process that
  did not perform the disarm. Falsified by any read that still returns it.

## Test list

- success: an arm written by one process is read by a subprocess with every
  field equal.
- success: an arm inside its lifetime reads as live at an instant the test
  supplies, with no clock read inside the module.
- failure: an arm exactly at its expiry instant, and one instant after, both
  read as absent, and one instant before reads as live.
- failure: constructing the submit value directly is impossible, proven by
  attempting every public path the module exposes rather than by asserting the
  absence of one name.
- failure: an arm whose recorded configuration hash differs from the current
  one is still readable, because detecting that mismatch is UNIT-034's job and
  this unit must not silently hide the arm from the code meant to compare it.
- restart: disarm in one process, then read from another, returns absent.
- restart: a store written, closed, and reopened yields the same arm, so
  durability is proven by reopening rather than by the write returning.
- no-trade: with no arm ever written, a read returns absent and raises nothing,
  because an unarmed system is the normal resting state and not an error.

## Verification

```bash
uv run pytest tests/execution/test_arm.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
