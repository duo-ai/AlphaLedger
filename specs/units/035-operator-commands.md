---
id: UNIT-035
title: Give an operator the arm, disarm, halt, and flatten commands
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-032, UNIT-034]
paths: src/alphaledger/cli.py, tests/test_cli.py
---

## Delegated to mazwy

Assigned to `mazwy` on 2026-08-31 by the user, together with the other five
units of feature 001. These are execution lane paths rather than research ones,
so the roster in `AGENTS.md` is amended to record the exception rather than
leaving it to be inferred. `preferred_runtime` is `claude` because that is the
runtime the owner runs, and `scripts/dispatch.sh` refuses a Claude owner by
design, so these are claimed and worked in a session with worktree isolation
rather than dispatched.

## C1 and C6, resolved 2026-09-04

C1 reached this unit through UNIT-034 and UNIT-031 and is closed at the source
by UNIT-036 and UNIT-031.

C6 said this unit performs arming and disarming while no unit owned writing
those transitions to the ledger, leaving a hole in the audit trail exactly
where a human took responsibility. It is closed by assignment rather than by
adding a second writer here: UNIT-032 now appends the ledger transition and
changes the arm store in one operation, ledger first, so an operator command
that reaches UNIT-032 at all is recorded whether or not a scan follows it. This
unit calls UNIT-032 and inherits that guarantee, and it must not write the
transition itself, because two writers for one fact is how two durable truths
come to disagree.

The obligation this leaves here is narrower and is now AC-8: every command this
unit exposes must reach its durable effect through UNIT-032 or UNIT-034, and
none may change trading state directly.

## Problem

The arm is the one moment a human takes responsibility for what follows, and
there is no way to perform it. There is also no way to halt or flatten, and
under a scheduled invocation model there may be no process running between
scans, so neither can be an interrupt to a loop. Both have to be things a
person starts.

Operator here means the human who arms, and the word is used consistently.

## Source of truth

- `specs/features/001-autonomous-session/spec.md`, criteria 4a and 13, and the
  Clarifications entry on the two step arm.
- `options-alpha-agent-design.md` section 11, which says one explicit arm
  action enables a frozen configuration and that disarm, emergency halt, and
  manual flatten remain available.
- `.claude/rules/30-execution.md` bullets 2 and 8.

## Scope

In:

- A two step arm. The first step displays the frozen configuration hash and the
  limits it implies; the second arms only when the operator supplies that exact
  hash.
- Disarm.
- Halt and flatten as their own invocations an operator starts at any moment.
- Exit statuses that distinguish refused from failed, so an operator and a
  script can both tell what happened.

Out:

- Writing the arm record. UNIT-032 owns its shape, durability, and expiry; this
  unit calls it.
- Running a session. UNIT-034 owns that; halt and flatten here invoke it.
- Deciding whether a flatten succeeded. UNIT-017 is merged and reports that,
  and its report must not be presented as a guarantee.

## Contract

`alphaledger.cli`, using `argparse` from the standard library. The surface is
five commands with one argument between them, which does not earn a dependency.

The arm display shows the configuration hash and the limits that hash covers,
so the operator reads what they are arming rather than a bare digest. The
confirm step refuses unless the supplied hash equals the currently committed
one, so a configuration edited between the two steps refuses rather than arms
silently.

Flatten reports what was attempted, what is confirmed closed by broker truth,
and what remains open. It never reports success as a guarantee, per rule
bullet 8, and a partial or failed flatten leaves the system disarmed.

## Acceptance criteria

- AC-1: arming without supplying a hash refuses. Falsified by an arm created by
  the display step alone.
- AC-2: a supplied hash that does not equal the currently committed
  configuration hash refuses. Falsified by an arm created after the
  configuration changed between the two steps, which is the drift design
  section 15 requires to be caught.
- AC-3: the display step creates nothing. Falsified by any durable record
  written before the confirm step.
- AC-4: halt and flatten run without a scheduled invocation in progress.
  Falsified by either requiring a running session, which under this model would
  make them unavailable exactly when a position is moving.
- AC-5: a flatten that does not confirm every position closed reports what
  remains open and leaves the system disarmed. Falsified by a report that reads
  as success while a position is open, or by an armed system afterwards.
- AC-6: no command prints a credential. Falsified by a sentinel secret in any
  output, including error output.
- AC-7: exit statuses distinguish success, refusal, and failure. Falsified by
  a refusal and a failure sharing a status, which would make a wrapper script
  unable to tell a safety refusal from a bug.

## Test list

- success: the display step prints the hash and the limits, and writes nothing.
- success: arming with the displayed hash creates a live arm.
- success: disarm makes the arm read as absent.
- failure: arming with a stale hash, after the configuration changed, refuses
  and names the mismatch.
- failure: arming with no hash refuses.
- failure: a flatten that leaves a position open reports it and disarms,
  asserted on the report and on the arm state rather than on the exit status
  alone.
- failure: every command run with a sentinel credential in the environment
  prints it nowhere.
- restart: halt and flatten succeed with no session process running, which is
  the ordinary state between scans.
- no-trade: disarming an already disarmed system succeeds and changes nothing,
  because an operator reaching for the safety control twice must not be
  punished for it.

## Verification

```bash
uv run pytest tests/test_cli.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
