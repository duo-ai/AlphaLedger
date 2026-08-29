---
id: UNIT-015
title: Reconcile broker truth and recover after restart
lane: execution
state: in_review
owner: pablo/codex
branch: feature/015-broker-reconciliation
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-011, UNIT-012]
paths: src/alphaledger/execution/reconcile.py, tests/execution/test_reconcile.py
claimed_at: 2026-08-29T11:43:30Z
---

## Problem

UNIT-012 resolves one order's state when queried by its own client order id,
and its own Out section explicitly excludes looping across many orders,
reading activities or positions, and deciding anything about a position the
broker reports that no known order explains. It hands all three to this unit.
Without something that aggregates broker truth across every locally known
order, every currently open broker order, every held position, and the
activities that attribute a position to an intent, a restart or a scheduled
check cannot tell a position under our own management from one nobody can
account for, and rule bullet 5 below has no code path enforcing it.

## Source of truth

- `.claude/rules/30-execution.md`, bullets 5 and 6.
- `options-alpha-agent-design.md` section 11, entry step 5 and the exit
  paragraph; section 12; section 15, the rows for an unknown submission
  result, a partial or working order beyond budget, and a position existing
  without ledger state.
- `project-state/DECISIONS.md`, D-015 and D-023.
- `specs/units/012-order-state-machine.md`, whose Out section assigns this
  unit the scheduled reconcile loop and orphan-position recovery, and whose
  Handoff notes record the review round that made `RecordedSubmissionAttempt`
  require a durable record without saying where that record is stored.
- `specs/units/011-order-schema-adapter.md`, whose Contract and Handoff notes
  explain why `BrokerActivity` carries `order_id` and why `BrokerPosition`
  exists at all: reconciliation is the reason, not an afterthought.

## Scope

In:

- Aggregating `alphaledger.execution.lifecycle.recover_submission` across
  every locally known order in one call, not just one order at a time.
- Detecting a broker order the broker currently holds open that no known
  order explains.
- Detecting a broker position not explained by any known order: first, by
  symbol coverage, and second, by whether at least one activity attributes
  that symbol to a known order's confirmed broker identity.
- One aggregate `ReconciliationReport` combining all of the above into a
  single `blocks_new_entries` boolean and a set of named reasons, callable
  identically at process startup and on every later scheduled cycle, since it
  takes a fresh snapshot of broker truth and locally known orders on each call
  and performs no I/O and holds no state of its own between calls.
- Failing closed independently per broker-truth boundary. A failure fetching
  open orders, positions, or activities does not fall back to an empty
  sequence; it blocks new entries on its own, the same as an unavailable order
  lookup, and one boundary recovering does not compensate for another still
  failing.

Out:

- Transport, endpoint assertion, and redirect handling (UNIT-010).
- Schema parsing and payload hashing (UNIT-011). This unit consumes
  `BrokerOrder`, `BrokerActivity`, and `BrokerPosition` values that already
  exist; it never parses raw broker JSON itself.
- The per-order state machine, the transition table, id derivation, and the
  duplicate-submission guard (UNIT-012). This unit calls `recover_submission`
  and `blocks_new_entries` and defines no second opinion about which states
  are unsafe or which transitions are legal.
- Where a submission attempt or a known order's local state is durably
  written and read. Design section 13 lists "order requests, responses,
  replacements, fills, and reconciliations" among the append-only ledger
  records, so that write is a ledger obligation, assigned to UNIT-016, which
  is currently a backlog row in `specs/000-INTAKE.md` with no intake file and
  nothing implementing it. This unit accepts `KnownOrder` values already
  materialized by whatever eventually reads that store, exactly as
  `recover_submission` already accepts `recorded_attempt` and `local_state`
  materialized rather than looked up. A `KnownOrder` carrying no recorded
  attempt is refused here (AC-1), which is the one place the inherited
  obligation becomes observable in this unit's own behavior.
- Quantity-level reconciliation: matching a position's exact signed size
  against the sum of its attributed fills, which can span several legs and
  several orders on one symbol. The check this unit performs is presence of
  attribution, not exact quantity agreement; the stronger check is real and is
  future work, not this pass.
- The scheduled trigger itself, meaning the timer, cron entry, or event loop
  that calls `reconcile` at startup and again on a fixed interval.
  `.claude/rules/40-tests.md` forbids wall-clock dependence in tests, and
  every sibling execution unit performs no I/O of its own; both point away
  from building a real scheduler here. `reconcile` is trigger-agnostic by
  construction, so the same function serves both callers. No unit currently
  owns the trigger.
- The risk approval token (UNIT-013), enumerating real chains and exact
  payoffs (UNIT-014), the bounded limit-price ladder (UNIT-018, not UNIT-013;
  `specs/000-INTAKE.md` corrected that reference on 2026-08-29, after UNIT-011
  and UNIT-012 were each written pointing at UNIT-013 before the ladder had
  its own row), the ledger itself (UNIT-016), and the kill switch and
  emergency flatten (UNIT-017).

## Contract

`alphaledger.execution.reconcile`, importing from `alphaledger.execution.lifecycle`
and `alphaledger.execution.orders`, never the reverse.
`alphaledger.execution.__init__` carries a docstring and no re-exports, per
UNIT-012's own note; this unit adds none either, so it stays inside its two
declared paths.

```python
ORDER_NOT_RECONCILED_REASON: Final[str] = "order_not_reconciled"
UNEXPLAINED_ORDER_REASON: Final[str] = "unexplained_order"
UNEXPLAINED_POSITION_REASON: Final[str] = "unexplained_position"


class BrokerTruthSource(Protocol):
    def open_orders(self) -> Sequence[BrokerOrder]: ...
    def positions(self) -> Sequence[BrokerPosition]: ...
    def activities(self) -> Sequence[BrokerActivity]: ...


@dataclass(frozen=True, slots=True)
class KnownOrder:
    client_order_id: str
    recorded_attempt: RecordedSubmissionAttempt | None
    local_state: OrderState | None
    covered_symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class OrderReconciliation:
    client_order_id: str
    decision: RecoveryDecision


@dataclass(frozen=True, slots=True)
class UnexplainedOrder:
    order: BrokerOrder
    reason: str


@dataclass(frozen=True, slots=True)
class UnexplainedPosition:
    position: BrokerPosition
    reason: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    orders: tuple[OrderReconciliation, ...]
    unexplained_orders: tuple[UnexplainedOrder, ...]
    unexplained_positions: tuple[UnexplainedPosition, ...]
    blocks_new_entries: bool
    reasons: tuple[str, ...]


def reconcile(
    order_lookup: BrokerOrderLookup,
    truth: BrokerTruthSource,
    known_orders: Sequence[KnownOrder],
) -> ReconciliationReport: ...
```

`BrokerOrderLookup`, `OrderState`, `RecordedSubmissionAttempt`,
`RecoveryAction`, `RecoveryDecision`, `blocks_new_entries`, and
`recover_submission` are `alphaledger.execution.lifecycle`, unchanged.
`BrokerOrder`, `BrokerActivity`, and `BrokerPosition` are
`alphaledger.execution.orders`, unchanged.

`BrokerTruthSource` is deliberately one Protocol with three methods rather
than three separate ones, so a single in-memory test fixture can satisfy it
and `BrokerOrderLookup` together with one object. Every method returns a
snapshot; nothing about the split carries meaning beyond that. An empty
sequence from any method means the broker reports nothing on that axis and
permits entries. An exception from any one of the three, or from
`order_lookup.order_by_client_id`, means broker truth on that axis is
unavailable and blocks new entries on its own, using
`alphaledger.execution.lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON`, the same
reason `recover_submission` already uses for its own lookup failure. One
shared reason for every unavailable-boundary case is deliberate: which
boundary failed is a fact the test that exercises it holds, not a fact this
report's reason strings need to carry separately.

For every `KnownOrder`, `reconcile` calls `recover_submission` exactly as
UNIT-012 defines it. A `RecoveryAction.BLOCK` result contributes its own
`decision.reason`. A `RecoveryAction.ADOPT_EXISTING` result additionally
contributes `ORDER_NOT_RECONCILED_REASON` whenever
`blocks_new_entries(decision.state)` is true. By construction that is every
state `recover_submission` can adopt from broker truth: broker status never
maps to `OrderState.RECONCILED`, since reaching it is a local step taken only
once an outcome is booked, so a known order still present in this reconciliation
pass is, by definition of being in the input at all, not yet reconciled.

An entry of `truth.open_orders()` is an unexplained order when its
`client_order_id` matches no `KnownOrder.client_order_id`.

A `BrokerPosition` from `truth.positions()` is explained only if both hold:
its `symbol` is in some `KnownOrder.covered_symbols`, and at least one entry
of `truth.activities()` shares that symbol and has an `order_id` equal to the
`broker_id` of a `BrokerOrder` this call obtained for some `KnownOrder` by
calling `order_lookup.order_by_client_id` a second time. `broker_id` is
immutable for a given `client_order_id` once the broker assigns it, so this
second call cannot disagree with the one inside `recover_submission` in any
way that matters. Failing either half makes the position unexplained.

`reasons` is the deduplicated tuple of every distinct reason that
contributed, in the order first observed. `blocks_new_entries` is true
exactly when `reasons` is non-empty.

Because every `ADOPT_EXISTING` order contributes `ORDER_NOT_RECONCILED_REASON`,
`blocks_new_entries` is already true in any call carrying at least one known
order, independent of whether unexplained-order or unexplained-position
detection exists at all. A test for either of those two behaviors therefore
has to assert on membership in `unexplained_orders` or `unexplained_positions`
and on the specific reason string; asserting only `blocks_new_entries` in a
scenario that also carries a known order proves nothing about the behavior it
names.

Two obligations fall on the caller building `KnownOrder` and
`BrokerTruthSource`, not on this function, which cannot check either.
`covered_symbols` must list every leg symbol the order actually touches.
Listing too many is merely overcautious, since it can only turn an explained
position into a false unexplained one and fail closed. Listing too few can
silently explain a real orphan, which is the one failure direction this unit
exists to prevent. `truth.activities()` must return enough history to
attribute every position currently held, not just recent activity; a feed
scoped to "since the last cycle" would flag a stable multi-day position as
unexplained on every single call and disarm entries permanently, which is
fail closed but makes the unit unusable rather than unsafe.

## Assumptions

- The durable store for `RecordedSubmissionAttempt` and for a known order's
  `local_state` is a ledger write, owned by UNIT-016, which has no intake
  file yet. `KnownOrder` accepts both already materialized.
- Unexplained-order detection is scoped to currently open broker orders, not
  the broker's full historical order list, since a closed order we do not
  recognize is not live risk the way an open one is. This may need revisiting
  once UNIT-016 exists and can say what "historical" should mean here.
- Position attribution stops at "at least one activity attributes this symbol
  to a known broker id." It does not reconcile exact quantity across legs and
  orders on one symbol; that stronger check is future work.
- One shared `BROKER_TRUTH_UNAVAILABLE_REASON` covers every case where an
  injected boundary raised, rather than one new constant per boundary, per
  `AGENTS.md`'s simplicity guidance; the boundary that failed is the test's
  concern, not the report's.

## Acceptance criteria

- AC-1: a `KnownOrder` whose `recorded_attempt` is `None` resolves to
  `RecoveryAction.BLOCK` with reason `submission_attempt_record_required`,
  and the report's `blocks_new_entries` is true. This is the observable
  carrying UNIT-012's inherited obligation into this unit: a known order
  given without a durably recorded attempt is refused, never silently
  adopted or ignored.
- AC-2: reconciling at least three `KnownOrder` values in one call produces
  one `OrderReconciliation` per input, in the same order, each resolved
  independently; a defect that resolves only the first or last input, or
  silently drops one, fails this.
- AC-3: broker truth overrides local state in both directions inside one
  call: a `KnownOrder` with `local_state=OrderState.WORKING` against a broker
  answer of `FILLED`, and a separate `KnownOrder` with
  `local_state=OrderState.RECONCILED` against a broker answer that is not
  `RECONCILED`, both yield the broker's answer. `local_state` never appears
  in the returned decision's `state` in either case.
- AC-4: an open broker order whose `client_order_id` matches no
  `KnownOrder` appears in `unexplained_orders` with `UNEXPLAINED_ORDER_REASON`,
  tested with every supplied `KnownOrder` resolving cleanly to
  `RecoveryAction.ADOPT_EXISTING`. Asserting only that `blocks_new_entries` is
  true does not satisfy this: that boolean is already true in this exact
  scenario from `order_not_reconciled` alone, whether or not unexplained-order
  detection exists.
- AC-5: a broker position whose `symbol` is covered by no `KnownOrder` is
  reported in `unexplained_positions` with `UNEXPLAINED_POSITION_REASON`.
- AC-6: a broker position whose `symbol` is covered by a `KnownOrder`, but for
  which every activity sharing that symbol attributes to a different order's
  `broker_id` or to none at all, is also reported unexplained. The test
  exercising this constructs such an activity; it does not merely omit
  activities, which would leave the symbol-coverage half of AC-5 doing all
  the work and the attribution half unproven. As in AC-4, asserting only
  `blocks_new_entries` does not satisfy this: the scenario's `KnownOrder` is
  itself unreconciled, so the boolean is already true from
  `order_not_reconciled` regardless of whether the attribution check exists;
  the test must assert on membership in `unexplained_positions` and on
  `UNEXPLAINED_POSITION_REASON` specifically.
- AC-7: `truth.open_orders()`, `truth.positions()`, `truth.activities()`, and
  `order_lookup.order_by_client_id` each independently raising are four
  separate test cases. `truth.open_orders()` and `truth.positions()` are
  exercised with otherwise-empty `known_orders` and truth, since both are
  queried on every call regardless of what else is present. `truth.activities()`
  is exercised with at least one `KnownOrder` and at least one position whose
  symbol that order covers, since an implementation may only need to consult
  activities when there is a covered position to attribute, and a fixture
  with no position could pass this case without ever reaching the call.
  `order_lookup.order_by_client_id` is exercised with at least one
  `KnownOrder`, since an empty `known_orders` never calls it. In every one of
  the four, `reasons` contains `BROKER_TRUTH_UNAVAILABLE_REASON`. Asserting
  only `blocks_new_entries` is not sufficient for the `truth.activities()`
  case: that `KnownOrder`'s own lookup succeeds and independently contributes
  `order_not_reconciled`, so the boolean is already true whether or not the
  activities failure is handled at all.
- AC-8: empty `truth.open_orders()`, empty `truth.positions()`, empty
  `truth.activities()`, and an empty `known_orders` together produce a
  report with `blocks_new_entries` false and an empty `reasons`. Broker
  silence on every axis permits entries and is not conflated with AC-7's
  failure case; a test asserting only one of the two is not sufficient.
- AC-9: this module calls `alphaledger.execution.lifecycle.blocks_new_entries`
  and defines no second predicate over which states are unsafe. A test
  parameterized over every `BrokerOrderStatus` that `recover_submission` can
  adopt, `SUBMITTED`, `WORKING`, `PARTIAL`, `FILLED`, `CANCEL_PENDING`,
  `CANCELED`, `EXPIRED`, and `REJECTED`, confirms `ORDER_NOT_RECONCILED_REASON`
  is contributed for every one, `FILLED` included, since none of them is
  `OrderState.RECONCILED`. That state is unreachable from broker truth by
  construction: no `BrokerOrderStatus` maps to it, so no test can observe its
  absence from the negative side, and this intake records that reasoning
  rather than asserting an unobservable case.
- AC-10: calling `reconcile` twice with two separately constructed but
  equal-by-value `BrokerTruthSource` fixtures and equal `known_orders`
  produces two equal `ReconciliationReport` values. The function takes no
  clock and holds no state between calls, so a second call standing in for a
  later scheduled cycle behaves exactly like the first.

## Test list

- success: reconciling three known orders in one call resolves each
  independently and returns one `OrderReconciliation` per input, in order.
- success: an open broker order with no matching known order appears in
  `unexplained_orders` with `unexplained_order`, tested with every known
  order resolving cleanly; asserting only `blocks_new_entries` does not pass,
  since a known order already makes it true on its own.
- failure: a `KnownOrder` with `recorded_attempt=None` blocks with
  `submission_attempt_record_required`.
- failure: `truth.open_orders()` raising, with empty `known_orders` and an
  otherwise-empty truth, puts `broker_truth_unavailable` in `reasons`; the
  same empty scenario without the raise is AC-8's no-trade case, so the pair
  proves the raise is what changed the outcome.
- failure: `truth.positions()` raising, under the same empty scenario, puts
  `broker_truth_unavailable` in `reasons`.
- failure: `truth.activities()` raising, with one `KnownOrder` and one
  position whose symbol it covers so the call is actually reached, puts
  `broker_truth_unavailable` in `reasons`; asserting only `blocks_new_entries`
  does not pass, since that known order's own successful lookup already makes
  it true.
- failure: `order_lookup.order_by_client_id` raising, with one `KnownOrder`
  so the lookup is actually reached, puts `broker_truth_unavailable` in
  `reasons`.
- failure: a position whose symbol matches no known order appears in
  `unexplained_positions` with `unexplained_position`.
- failure: a position whose symbol matches a known order, but whose only
  same-symbol activity attributes to a different order's `broker_id`, appears
  in `unexplained_positions` with `unexplained_position`; asserting only
  `blocks_new_entries` does not pass, since the matching known order already
  makes it true through `order_not_reconciled`.
- restart: local state `WORKING` against broker truth `FILLED` yields
  `FILLED`.
- restart: local state `RECONCILED` against broker truth that is not
  `RECONCILED` yields the broker's actual state, not the local belief that it
  was already done.
- restart: reconciling the same three inputs twice, standing in for a
  startup call followed by the next scheduled cycle, produces two equal
  reports.
- no-trade: empty open orders, empty positions, empty activities, and no
  known orders together produce `blocks_new_entries=False` and an empty
  `reasons`.
- no-trade: a known order that resolves to `RecoveryAction.ADOPT_EXISTING`
  still blocks new entries with `order_not_reconciled`, even though nothing
  is actually wrong with it; it is simply not finished. Parameterized over
  every `BrokerOrderStatus` `recover_submission` can adopt, `FILLED` included,
  rather than asserted on one example.

## Verification

```bash
uv run pytest tests/execution/test_reconcile.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
