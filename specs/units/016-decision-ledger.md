---
id: UNIT-016
title: Append-only decision and trade ledger
lane: execution
state: in_review
owner: pablo/codex
branch: feature/016-decision-ledger
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-012, UNIT-020]
paths: src/alphaledger/ledger/**, tests/ledger/**
claimed_at: 2026-08-29T17:31:32Z
reviewed_by: execution-safety-reviewer
review_verdict: block
reviewed_at: 2026-08-29T17:52:00Z
review_log: [block]
---

## Problem

Two obligations exist today with nothing behind them. Design section 13 says
every candidate, including a `no_trade` one, is stored append-only; nothing
currently persists a decision at all, so that claim has no data behind it.
More concretely, `alphaledger.execution.lifecycle.decide_submission` and
`recover_submission` both require a caller-held `RecordedSubmissionAttempt` as
evidence that a submission attempt was durably recorded before transport, and
`alphaledger.execution.reconcile.reconcile` requires a `KnownOrder` carrying
that same value plus a `local_state`. Neither `lifecycle.py` nor `reconcile.py`
performs any I/O, by their own declared scope, so neither can produce the value
its own contract demands. Every caller of either module is currently unable to
satisfy a precondition the module itself states, which blocks paper submission
from ever being safely armed.

## Source of truth

- `options-alpha-agent-design.md` section 13, the append-only records list and
  the "secrets... never enter the ledger" line.
- `AGENTS.md`, the engineering boundaries list (ledger code is append-only and
  records every decision, including no-trades) and the "prefer a well
  established package" rule.
- `.claude/rules/01-safety.md`, the append-only audit path bullet.
- `project-state/DECISIONS.md`, D-015 (store integrity checked on open),
  D-017 (what belongs in committed, hashable evidence versus the environment),
  and D-023 (why `client_order_id` is derived before any approval, which is
  why it is this unit's identity key for a submission attempt).
- `specs/units/012-order-state-machine.md`, the `RecordedSubmissionAttempt`
  contract and its Handoff notes recording the review round that created it.
- `specs/units/015-broker-reconciliation.md`, Scope Out and Assumptions, which
  assign the durable store behind `RecordedSubmissionAttempt` and a known
  order's `local_state` to this unit by id.
- `specs/units/024-splits-and-trial-registry.md`, Handoff notes, "Two
  deviations from this intake", for the precedent of importing
  `alphaledger.data.storage.AppendOnlyStore` directly rather than duplicating
  an append-only writer.

## Scope

In:

- A generic, content-addressed append-only mechanism, reusing
  `alphaledger.data.storage.AppendOnlyStore` by import, that records a
  caller-supplied payload under a caller-chosen `subject_id` and `kind`. Every
  category section 13 names, including one no unit has been written to produce
  yet, can be recorded through this mechanism without this unit needing to
  know that category's internal shape.
- The specific, load-bearing case: durably recording a submission attempt
  before transport and returning `alphaledger.execution.lifecycle.RecordedSubmissionAttempt`,
  and reconstructing that same value after a restart. This is the obligation
  `specs/units/012-order-state-machine.md` states and cannot enforce, and
  which `specs/units/015-broker-reconciliation.md` assigns here by name.
- Durably recording an observed order state as a fact, and reporting the most
  recently recorded one for a given `client_order_id`. This is the other half
  of the obligation `specs/units/015-broker-reconciliation.md` assigns here,
  the materialization of a `KnownOrder.local_state`.
- Recording a `no_trade` decision through the same generic mechanism as any
  other decision, with no other entry required to exist first.

Out:

- Transport and endpoint assertion (UNIT-010).
- Schema parsing and payload hashing (UNIT-011).
- The order state machine, its transition table, and the legality of a
  transition (UNIT-012). This unit records a state a caller already validated
  as a fact; it does not decide whether reaching it was legal, and it defines
  no second opinion about which transitions are safe.
- Producing a risk approval (UNIT-013) or enumerating a structure (UNIT-014).
- Aggregating broker truth across many orders, positions, and activities
  (UNIT-015). This unit is the durable store `KnownOrder` values are read from
  once materialized elsewhere; it does not itself query a broker or assemble
  a `KnownOrder`.
- The kill switch and emergency flatten (UNIT-017).
- The bounded entry price ladder (UNIT-018).
- The dashboard. Section 13 covers both the ledger and a dashboard reading it;
  presentation code reads projections and never changes trading state, per
  `AGENTS.md`, and nothing here renders one.
- Defining a payload shape for a category no unit yet produces: exits,
  realized or conservative-adjusted P&L, and shadow-book outcomes. Section 13
  names all three, but no unit exists to emit any of them, and inventing a
  shape ahead of the unit that actually produces one would be guessing at a
  contract nobody has written. `EvidenceCard`, `Forecast`, `StructurePlan`,
  and `RiskApproval` already exist as frozen records; converting one of those
  into a payload for the generic method is the job of whichever unit produces
  it, not this one.
- Keeping a secret out of the ledger. Section 13 states secrets, full
  credentials, and sensitive headers never enter it, but nothing here can
  distinguish a secret string from an ordinary field; see Assumptions for the
  structural mitigation this unit does provide.
- Preventing two racing processes from both writing at once.
  `specs/units/024-splits-and-trial-registry.md` accepts the identical gap for
  its own registry, for the identical reason: a lock is only worth having if
  it is tested, and a deterministic concurrency test needs either a sleep,
  which `.claude/rules/40-tests.md` forbids, or a synchronisation mechanism
  this unit has no other reason to own. This unit detects the resulting
  conflict on read and fails closed; it does not prevent the race.

## Contract

`alphaledger.ledger`, carrying a docstring and no re-exports, matching
`alphaledger.execution`'s own stated convention so this unit stays inside its
declared paths. `alphaledger.ledger.decisions` holds everything below,
importing from `alphaledger.data.storage`, `alphaledger.domain.contracts`, and
`alphaledger.execution.lifecycle`, never the reverse.

```python
LedgerEntryId = NewType("LedgerEntryId", str)

SUBMISSION_ATTEMPT_KIND: Final[str] = "submission_attempt"
ORDER_STATE_KIND: Final[str] = "order_state"


class SubmissionAttemptConflictError(ValueError): ...


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: LedgerEntryId
    subject_id: str
    kind: str
    payload: Mapping[str, str]
    recorded_at: datetime


class DecisionLedger:
    def __init__(self, store: AppendOnlyStore) -> None: ...

    def record_decision(
        self,
        subject_id: str,
        kind: str,
        payload: Mapping[str, object],
        recorded_at: datetime,
    ) -> LedgerEntryId: ...

    def record_submission_attempt(
        self,
        client_order_id: str,
        payload: Mapping[str, object],
        recorded_at: datetime,
    ) -> RecordedSubmissionAttempt: ...

    def submission_attempt_for(
        self, client_order_id: str
    ) -> RecordedSubmissionAttempt | None: ...

    def record_order_state(
        self,
        client_order_id: str,
        state: OrderState,
        recorded_at: datetime,
    ) -> LedgerEntryId: ...

    def latest_order_state_for(self, client_order_id: str) -> OrderState | None: ...

    def entries_for(self, subject_id: str) -> tuple[LedgerEntry, ...]: ...
```

`AppendOnlyStore` and `StoreCorruptionError` are `alphaledger.data.storage`,
unchanged. `OrderState` and `RecordedSubmissionAttempt` are
`alphaledger.execution.lifecycle`, unchanged.

Nothing here reads a clock; `recorded_at` is always supplied by the caller,
matching `alphaledger.forecast.registry` and `alphaledger.forecast.splits`, so
a ledger can be rebuilt from a recorded run and still say the same thing.
`subject_id`, `kind`, and `client_order_id` must be non-blank strings, and
`payload` must not be empty, refused the same way
`alphaledger.data.recorder`'s own payload check already is: an entry with
nothing in it records nothing observable.

**Payload values.** Restricted to `str`, `int` (never `bool`), `Decimal`, and
`datetime`, matching the same scalar bound `alphaledger.domain.contracts`
already places on a `StructurePlan` leg. A `float` anywhere in a payload is
refused, naming the field, for the same reason `alphaledger.domain.contracts.money`
refuses one: a price or a probability that round-trips through binary
floating point is not the number that was decided. Every value is stored and
read back as a string: `str` unchanged, `int` via `str(value)`, `Decimal` via
`str(value)` with no rounding or quantization applied, and `datetime` via its
UTC isoformat after `alphaledger.domain.contracts.require_utc`. Quantizing a
`Decimal` the way `money()` does, to four places with `ROUND_HALF_EVEN`, is
deliberately not done here: this is an evidence ledger, and silently changing
a recorded value's precision would falsify what it claims to have recorded.
A sequence-shaped field, `evidence_spans`, `raw_data_hashes`, and
`failed_gates` are the three section 13 already names, has no representation
of its own; a caller joins it into one delimited string or spreads it across
several numbered keys. This is a convention decided now, not a
`[NEEDS CLARIFICATION]`, specifically so two future callers do not each invent
one. Widening `DecisionLedger` to accept a native sequence value later is
additive and does not change anything recorded under this convention.

**`record_decision`** is idempotent by full content: identical `subject_id`,
`kind`, `payload`, and `recorded_at` recorded twice yield one entry and one
`LedgerEntryId`, matching `alphaledger.data.recorder.Recorder.record` and
`alphaledger.forecast.registry.TrialRegistry.register`. A later call that
differs only in `recorded_at` is a second, distinct entry, both retained,
because a decision genuinely re-evaluated at a materially later instant, a
`no_trade` reached again the next day, is a new observation, not a duplicate
of the first. `record_decision` refuses `kind` equal to `SUBMISSION_ATTEMPT_KIND`
or `ORDER_STATE_KIND`; those identities belong to the two typed methods below,
which resolve idempotency differently, and allowing the generic method to
write under either name would let a caller bypass that resolution.

**`record_submission_attempt` and `record_order_state`** resolve idempotency
on `(client_order_id, kind, semantic fields)` alone, excluding `recorded_at`,
which is the deliberate opposite of `record_decision` above. The reason: a
caller retrying a submission attempt after a crash cannot supply the original
instant it no longer remembers, so treating `recorded_at` as part of identity
would make every crash-retry look like a new, conflicting fact rather than the
same one restated. Comparing must happen on the same normalized form the
entry was stored as: the incoming payload is converted through the same
string coercion described above before being compared to a previously stored
entry's payload, never compared as raw, uncoerced Python values. A test that
skipped this and compared a raw incoming `Decimal` or `datetime` against an
already-stringified stored value would see every legitimate retry as a
mismatch and raise `SubmissionAttemptConflictError` on the very case the
method exists to make safe; this is why the Test list below requires such a
value in the retry case.

For `record_submission_attempt`: a first call for a `client_order_id` appends
one entry and returns `RecordedSubmissionAttempt(client_order_id, record_id=<entry id>)`.
A later call for the same `client_order_id` whose coerced payload matches the
first appends nothing and returns the same value. A later call whose coerced
payload differs raises `SubmissionAttemptConflictError` before anything is
appended, and the first recorded attempt is unchanged.

The caller obligation this creates, which nothing here can enforce: call
`record_submission_attempt` and only afterward call the broker adapter.
Nothing in this module performs transport, so the ordering relative to an
external broker request is not something a test of this module can observe.
What is observable, and is exactly what AC-6 proves: `AppendOnlyStore.append`
flushes and fsyncs before it returns, so the bytes behind the returned
`RecordedSubmissionAttempt` are durable on disk by the time the call returns,
and a fresh `DecisionLedger` over the same store recovers the identical value
afterward. A caller that waits for the return value before transporting is
therefore provably safe; nothing here can prove a caller that does not wait
was not.

For `record_order_state`: each call appends the state as an observed fact and
performs no validation of whether reaching it was a legal transition; that
table is `alphaledger.execution.lifecycle`'s alone. `latest_order_state_for`
returns the state of the most recently appended `ORDER_STATE_KIND` entry for
one `client_order_id`, "most recent" meaning latest in append order, not by
any timestamp field. A caller that appends states out of order gets back a
locally wrong answer; this is accepted rather than guarded, because
`specs/units/015-broker-reconciliation.md` AC-3 already establishes that
broker truth overrides `local_state` in both directions whenever the two
disagree, so a wrong local value here is corrected at the next reconciliation
pass rather than acted on directly.

**`entries_for`** returns every entry recorded under one `subject_id`, in the
order first recorded, or an empty tuple if none exist. It carries no `kind`
filter; a caller wanting one kind filters the returned tuple itself.
`submission_attempt_for` and `latest_order_state_for` return `None`, never
raise, for a `client_order_id` nothing was ever recorded against. If more than
one distinct `SUBMISSION_ATTEMPT_KIND` entry is ever found for one
`client_order_id`, standing in for two processes that both passed the
write-time check before either appended, `submission_attempt_for` raises
`alphaledger.data.storage.StoreCorruptionError` rather than choosing one,
matching `alphaledger.forecast.registry.TrialRegistry.trials`'s identical
handling of two results found for one trial. A store holding a line
`AppendOnlyStore.read_all` cannot parse propagates that failure from every
read method here; none of them substitutes an empty result.

## Assumptions

- Reuse over a new implementation. `alphaledger.data.storage.AppendOnlyStore`
  already solves append-only, fsynced, corruption-detecting storage, and
  `specs/units/024-splits-and-trial-registry.md` already established the
  precedent of importing it directly rather than duplicating a second
  corruption implementation to keep in sync with the first. That precedent is
  research code importing a research-lane module; this unit is execution code
  importing one. The reasoning still holds because of what `AppendOnlyStore`
  is, not which lane wrote it: its own docstring says it "holds no index, no
  cache, and no notion of what a record means", which is a storage primitive,
  not a data adapter. `AGENTS.md`'s roster constrains which lane may *write*
  under `src/alphaledger/data/**`; D-010's disjoint-globs rule is about
  concurrent writers to one file, not about reading a merged, reviewed module
  from another lane. Any change to `alphaledger.data.storage` itself remains
  research-lane work and is a separate unit.
- The durable store behind `RecordedSubmissionAttempt` and `local_state` is
  accepted as this unit's obligation, per `specs/units/015-broker-reconciliation.md`.
- Sequence-shaped payload fields are not natively supported; a caller encodes
  one as a delimited string or several numbered keys. Decided now so two
  future callers do not each invent a convention.
- A secret cannot be kept out of the ledger by this unit's own logic, since a
  payload value is an opaque scalar to it. The structural mitigation already
  present: the payload is a flat, caller-supplied map with no implicit
  capture, no kwargs slurp, no serialized exception object, and no
  environment read, so nothing enters it that the caller did not explicitly
  name. Keeping a secret's value out remains the caller's obligation.
- `entries_for` has no `kind` filter. Filtering the returned tuple is a few
  lines at the call site rather than a second parameter with its own
  validation surface.
- Reviewed by `execution-safety-reviewer`, not `backtest-auditor`, because the
  load-bearing property here, the pre-transport submission-attempt guarantee,
  is an execution-safety property, matching the reviewer already assigned to
  `alphaledger.execution.lifecycle` and `alphaledger.execution.reconcile`.

## Acceptance criteria

- AC-1: two calls to `record_decision` with an identical `subject_id`, `kind`,
  `payload`, and `recorded_at` return the identical `LedgerEntryId`, and
  `entries_for(subject_id)` shows exactly one entry, not two.
- AC-2: two calls to `record_decision` with the same `subject_id`, `kind`, and
  `payload` but two different `recorded_at` values produce two distinct
  `LedgerEntryId` values, and `entries_for(subject_id)` returns both, in the
  order recorded. This is what proves `recorded_at` is genuinely part of
  `record_decision`'s identity, in direct contrast with AC-4.
- AC-3: `record_submission_attempt` immediately followed by
  `submission_attempt_for` on the same `client_order_id`, in the same
  process, returns an equal `RecordedSubmissionAttempt`.
- AC-4: `record_submission_attempt` called twice for one `client_order_id`
  with an identical payload, containing at least one `Decimal` and one
  `datetime` value, but two different `recorded_at` values, standing in for a
  caller retrying after a crash that cannot supply the original instant,
  returns two equal `RecordedSubmissionAttempt` values, and the store gains
  exactly one entry, not two. The `Decimal`/`datetime` requirement exists so a
  test cannot pass against an implementation that compares the incoming
  payload's raw values against an already-stringified stored payload and
  wrongly reports a conflict.
- AC-5: `record_submission_attempt` called a second time for one
  `client_order_id` with a payload that differs from the first recorded
  attempt raises `SubmissionAttemptConflictError` before anything is
  appended, and `submission_attempt_for` immediately afterward still returns
  the first attempt's value, unchanged.
- AC-6: a `DecisionLedger` constructed fresh over the same `AppendOnlyStore`
  path after an earlier instance recorded a submission attempt, standing in
  for a process restart, returns the identical `RecordedSubmissionAttempt`
  from `submission_attempt_for`. Neither method holds state outside the
  store, so a fresh instance returning anything else would mean the
  guarantee lived only in memory.
- AC-7: `record_order_state(id, OrderState.WORKING, t1)` followed by
  `latest_order_state_for(id)` returns `OrderState.WORKING`. Recording
  `OrderState.FILLED` afterward for the same id changes
  `latest_order_state_for(id)` to `FILLED`, while `entries_for(id)` still
  lists both, `WORKING` before `FILLED`. Recording `OrderState.WORKING` a
  second time at a different `recorded_at`, standing in for a retry, does not
  add a third entry; `entries_for(id)` still shows exactly one `WORKING`
  entry.
- AC-8: for a `client_order_id` or `subject_id` nothing has ever been
  recorded against, `submission_attempt_for` returns `None`,
  `latest_order_state_for` returns `None`, and `entries_for` returns an empty
  tuple; none of the three raises.
- AC-9: `record_decision` with a payload describing a `no_trade` outcome and
  its reasons succeeds and is retrievable through `entries_for`, with no
  entry of any other kind required to exist for that `subject_id` first.
  This is the observable form of `AGENTS.md`'s "`no_trade` is a valid and
  expected result": recording a refusal is not a degraded or partial write.
- AC-10: a payload value that is a `Decimal` with more than four decimal
  places is stored and, once the caller reconstructs a `Decimal` from the
  returned string, equals the original exactly; no money-style rounding is
  applied. A `datetime` payload value's UTC instant round-trips the same way
  through `require_utc` and its isoformat string. A `float` value anywhere in
  a payload raises before anything is appended, naming the field; a `bool`
  value is refused the same way despite being an `int` subclass.
- AC-11: a store whose file holds one line `AppendOnlyStore.read_all` cannot
  parse makes both `entries_for` and `submission_attempt_for` raise
  `StoreCorruptionError`; neither substitutes an empty or partial result.
- AC-12: two entries of kind `SUBMISSION_ATTEMPT_KIND` for one
  `client_order_id`, with two different payloads, written directly to the
  underlying store rather than through `record_submission_attempt`, standing
  in for two processes that both passed the write-time check before either
  appended, make `submission_attempt_for` raise `StoreCorruptionError`
  specifically, not any other exception, rather than silently choosing one.
- AC-13: `record_decision` raises when `kind` equals `SUBMISSION_ATTEMPT_KIND`
  or `ORDER_STATE_KIND`, tested for both constants separately.

## Test list

- success: two `record_decision` calls with identical arguments return the
  same `LedgerEntryId` and leave one entry (AC-1).
- success: two `record_decision` calls differing only in `recorded_at` leave
  two entries, both returned by `entries_for` in order, each with its own
  `recorded_at` (AC-2).
- success: `record_submission_attempt` then `submission_attempt_for` in one
  process returns an equal value (AC-3).
- success: `record_order_state` then `latest_order_state_for` returns the
  state recorded; recording a second, different state changes what
  `latest_order_state_for` reports while `entries_for` still lists both in
  order (AC-7).
- success: a `Decimal` payload value with five decimal places and a
  `datetime` payload value each round-trip, via the caller reconstructing
  them from the returned strings, to a value equal to the original (AC-10).
- success: a `no_trade` decision recorded via `record_decision` for a
  `subject_id` with no other entry anywhere in the store is retrievable via
  `entries_for` (AC-9).
- failure: `record_submission_attempt` called a second time for one
  `client_order_id` with a differing payload raises
  `SubmissionAttemptConflictError`; `submission_attempt_for` afterward still
  returns the first attempt, unchanged (AC-5).
- failure: `record_decision` called with `kind=SUBMISSION_ATTEMPT_KIND`, and
  separately with `kind=ORDER_STATE_KIND`, raises in both cases (AC-13).
- failure: a payload containing a `float` value raises before anything is
  appended, naming the field; `entries_for` afterward is empty. A payload
  containing a `bool` value is refused the same way (AC-10).
- failure: a store pre-seeded with one unparseable line makes both
  `entries_for` and `submission_attempt_for` raise `StoreCorruptionError`
  (AC-11).
- failure: two `SUBMISSION_ATTEMPT_KIND` entries for one `client_order_id`
  with different payloads, written directly to the store, make
  `submission_attempt_for` raise `StoreCorruptionError` specifically (AC-12).
- restart: `record_submission_attempt` invoked twice with an identical
  payload containing a `Decimal` and a `datetime` value, but two different
  `recorded_at` values, returns the same `RecordedSubmissionAttempt` both
  times and leaves exactly one entry in the store; asserting only that
  neither call raises is not sufficient, the test asserts on the entry count
  and on both `record_id` values being equal (AC-4).
- restart: a second `DecisionLedger` constructed over the same store path
  after an earlier instance recorded a submission attempt still returns that
  exact `RecordedSubmissionAttempt` from `submission_attempt_for` (AC-6).
- restart: recording the identical order state twice for one
  `client_order_id`, at two different `recorded_at` values, does not
  duplicate the entry; `entries_for` still shows exactly one entry for that
  state (AC-7).
- no-trade: `submission_attempt_for`, `latest_order_state_for`, and
  `entries_for` each return an empty result, never raising, for an id nothing
  has ever been recorded against (AC-8).
- no-trade: a `no_trade` decision is recorded and read back with no other
  entry required to exist for that candidate first (AC-9).

## Verification

```bash
uv run pytest tests/ledger -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

- 2026-08-29 code review round one, `execution-safety-reviewer`, verdict block.
  One P1, confirmed against the code by the session before being recorded here.

  `record_order_state` coalesces against every prior entry for an id, not
  against the most recent one. The loop scans the whole history and returns the
  first entry whose state matches, appending nothing. So the legal sequence
  `partial`, then `cancel_pending`, then `partial` again records only the first
  two: the third observation finds the first `partial` and is dropped.
  `latest_order_state_for` then answers `cancel_pending` after a restart, which
  is not where the order is, and the ledger has no record that the transition
  happened.

  That sequence is not exotic. UNIT-012's transition table admits
  `cancel_pending` to `partial` deliberately, because a cancel can lose the race
  against a fill, and a machine that refused it would raise on something the
  broker really produces. The ledger has to hold what the state machine allows.

  This is worse here than a wrong answer would be elsewhere. An append-only
  audit path exists so that a decision can be reconstructed afterwards, and
  `.claude/rules/01-safety.md` requires it. A ledger that silently drops a real
  transition is not a shorter ledger, it is one that cannot be trusted to be
  complete, and nothing downstream can tell the difference.

  The correction is to coalesce only an immediate duplicate, comparing against
  the last appended entry for that id rather than searching the history. An
  idempotent retry of the same observation still writes once, which is the
  behaviour AC-7 wants, and a genuine recurrence appends.

  The regression must use a legal recurrence, `partial`, `cancel_pending`,
  `partial`, and assert both that the history holds three entries and that
  `latest_order_state_for` answers `partial` after reopening the store. Two
  existing order-state tests pass today without exercising recurrence at all.

  Three further test weaknesses were named and are worth fixing in the same
  pass, though none is blocking on its own: the immediate-retrieval test would
  pass against memory-only durability, and the Decimal and datetime retry test
  reuses one ledger, so it cannot see a normalisation defect that only appears
  on reopening. Both want a fresh ledger opened from the same path.

  Deliberately not carried into this unit, per D-022: live transport, the arm
  state, sizing, broker timeouts, stale data, and flattening. None is an
  acceptance criterion here and none is actionable inside
  `src/alphaledger/ledger/**`.
