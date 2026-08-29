---
id: UNIT-017
title: Evaluate the equity kill switch and report flatten completion
lane: execution
state: in_review
owner: pablo/codex
branch: feature/017-kill-switch
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-012, UNIT-015]
paths: src/alphaledger/execution/killswitch.py, tests/execution/test_killswitch.py
claimed_at: 2026-08-29T17:31:32Z
reviewed_by: execution-safety-reviewer
review_verdict: clear
reviewed_at: 2026-08-29T17:52:15Z
review_log: [clear]
---

## Problem

Two circuit breakers are named in the risk policy and neither has a code path.
Without a deterministic check, an equity drawdown that should halt the system
and force an exit instead runs on, because nothing observes the drawdown at
all. Without a way to know whether an emergency flatten actually closed
everything, a partial or failed flatten could be read as success by whatever
called it, which is exactly the false confidence `.claude/rules/30-execution.md`
forbids.

## Source of truth

- `options-alpha-agent-design.md` section 10, the peak-to-valley equity kill
  switch and daily realized-plus-unrealized loss stop rows.
- `options-alpha-agent-design.md` section 12, the exit trigger "the portfolio
  kill switch fires."
- `options-alpha-agent-design.md` section 15, the row "Daily/drawdown limit
  breached | Cancel entries, execute authorized flatten policy, halt". This one
  row is the warrant for both thresholds living in this unit: `specs/units/013-risk-approval-token.md`
  disclaims only the peak-to-valley switch, by this unit's title, and leaves
  the daily stop unassigned anywhere else.
- `.claude/rules/30-execution.md`, the hard rules on cancelling working entries
  and flattening before the cutoff, and its last bullet, quoted in full because
  it is this unit's safety heart: "Emergency flatten is observable and
  idempotent; failure escalates and keeps entry disabled. It is never
  presented as guaranteed liquidation."
- `project-state/DECISIONS.md` D-017, on why a threshold absent from
  `config/risk.toml` is a required parameter, not an invented constant, and
  D-023, on why a closing order's id is derived from its own price rather than
  from anything this unit produces.
- `specs/units/012-order-state-machine.md`, for `recover_submission`,
  `RecordedSubmissionAttempt`, and `RecoveryAction`, all consumed unchanged.
- `specs/units/015-broker-reconciliation.md`, whose `alphaledger.execution.reconcile`
  module this unit imports `KnownOrder` and `OrderReconciliation` from rather
  than redefining an equivalent pair, and whose aggregation shape, one
  independent per-target decision plus a deduplicated reason tuple, this unit
  mirrors.
- `specs/units/013-risk-approval-token.md`, the precedent for a threshold this
  codebase has not committed, `max_snapshot_age`, being a required explicit
  parameter rather than a guessed constant.
- `config/risk.toml`, read directly. It commits eight fields and none of them
  is a peak-to-valley or daily-loss fraction.

## Scope

In:

- `evaluate_kill_switch`, a pure comparison of an already-computed equity
  reading against two explicit threshold fractions, neither of which is
  committed in `config/risk.toml` today. See "Why the thresholds are
  parameters, not constants".
- `flatten`, an aggregation over locally known closing intents that mirrors
  `alphaledger.execution.reconcile.reconcile`'s shape: one independent decision
  per target plus a deduplicated set of reasons, callable identically on a
  fresh attempt and on every later retry, since it performs no I/O and holds no
  state between calls.
- Naming, by unit id, why cancelling working entry orders is not implemented
  here, rather than leaving that gap silent. See Out.

Out:

- Transport and paper-endpoint assertion (UNIT-010). This module performs no
  I/O.
- Building or parsing a closing order's payload (UNIT-011). This unit chooses
  no price and constructs no payload. A caller derives a closing order's
  economics and its id exactly as it would for any other order, through
  `alphaledger.execution.lifecycle.client_order_id`, before constructing the
  `KnownOrder` this unit consumes. Because price is one of that function's
  inputs, a retry at a new price yields a new id by construction, per D-023,
  so a rejected or stuck closing order has the same fail-closed retry path
  UNIT-012 already gives an entry order; this unit needs no separate mechanism
  for it.
- The per-order state machine, its transition table, and the duplicate
  submission guard (UNIT-012). `flatten` calls `recover_submission` unchanged
  and defines no second opinion about which states are unsafe.
- Risk approval and position sizing (UNIT-013). This module reads no account
  snapshot and approves nothing; an equity reading arrives already
  materialized as `EquityState`, exactly as `AccountSnapshot.equity` arrives
  already materialized to UNIT-013's `approve`.
- Enumerating chains or computing exact payoffs (UNIT-014).
- The scheduled reconcile loop, unexplained-order and unexplained-position
  attribution across the whole account, and orphan-position recovery
  (UNIT-015). `flatten` asks a narrower question than that unit does, whether
  one specific target's covered symbols are still held, not whether some known
  order explains a position; it consumes `KnownOrder` and `OrderReconciliation`
  from that unit's module rather than re-deriving broker state.
- The ledger (UNIT-016). Recording a kill-switch trigger, a flatten attempt, or
  its outcome is a ledger write. This module returns values for a caller to
  record; it writes nothing itself.
- The bounded entry price ladder (UNIT-018), and by the same reasoning any
  ladder for a rejected or stuck closing order, covered above under the order
  schema note.
- The session and arm state machine (owned by the orchestrator, not any unit,
  per UNIT-012's and UNIT-013's own scope notes). Nothing in this module calls
  `evaluate_kill_switch` from `flatten`. Deciding that a triggered kill switch
  should start a flatten, and deciding whether a fully flattened book may
  re-arm, is the orchestrator's job; this module supplies the two facts that
  decision needs and makes neither decision itself.
- Cancelling working entry orders. Design section 10's hard rules require
  "cancel all working entries when the system halts," and section 15 pairs
  cancellation with flatten in one row. A cancel is a distinct order-lifecycle
  transition, `cancel_pending`, already in UNIT-012's transition table, and no
  unit today owns a cancel's submission path the way UNIT-011 owns
  `build_mleg_order` for an entry. This unit closes held positions; it does
  not cancel working orders. Recorded here as an open gap, not left silent.
- Computing or tracking the peak-equity high-water mark, the session-start
  equity snapshot, or the window either one spans. See Assumptions.

## Why the thresholds are parameters, not constants

Design section 10 gives 1.5% of session-start equity for the daily loss stop
and 3.0% for the peak-to-valley kill switch. `config/risk.toml` commits eight
fields today and neither of these two is among them. Per D-017 a threshold
that is not committed and hashed cannot be invented in code, so
`daily_loss_stop_fraction` and `peak_to_valley_fraction` are required explicit
arguments to `evaluate_kill_switch`, exactly as `max_snapshot_age` is a
required argument to UNIT-013's `approve` for the same reason. The natural
long-term home for both is two new fields on `RiskConfig`, hashed into the run
manifest; that is a change to UNIT-004's files and belongs to whoever wires a
caller, not to this unit's declared paths.

## Why equality triggers

A limit stated as "3.0%" has to bind at 3.0%, or the switch enforces a laxer
limit than the one actually recorded. This is the opposite direction from a
permissive gate: UNIT-013's `entry_limit_bound` check treats equality as safe
because its rule is "must not exceed," a ceiling a candidate may touch. A kill
switch's rule is "must fire at or beyond," a floor a loss may not cross without
tripping it. `evaluate_kill_switch` therefore triggers when the observed
fraction is greater than or equal to the threshold, not only when it strictly
exceeds it.

## What confirms a target is closed

`flatten` looks at two independent things per target and does not let either
one stand in for the other.

The first is `alphaledger.execution.lifecycle.recover_submission`, called
exactly as `alphaledger.execution.reconcile.reconcile` already calls it,
unchanged. A `RecoveryAction.BLOCK` result, no recorded attempt, a mismatched
one, an ambiguous submission, an unknown order state, or an unavailable
broker, contributes its own reason. Unlike `reconcile`, `flatten` does not
additionally contribute a reason merely because a target resolves to
`RecoveryAction.ADOPT_EXISTING`. In `reconcile`, that contribution exists
because reaching `OrderState.RECONCILED` is a booking step no broker status
can produce, so an entry order that filled still has an open position ahead of
it and is correctly "not yet reconciled." Here the position itself is a fact
this module can observe directly, so a second, always-true copy of that same
signal would add nothing and would make the report's `blocks_new_entries`
field true for every non-empty call regardless of whether anything is actually
still open, which is not an observable worth returning.

The second is `positions.positions()`. A target's covered symbols are
compared against every broker-reported position with a nonzero signed
quantity; a match means the position is still held. A target whose closing
order cleanly resolves, at `OrderState.FILLED` among others, can still have a
covered symbol appear in `still_open_symbols`, because the filled order's own
quantity may have been smaller than the position, or a sibling leg may have
failed to fill. This is deliberate: a clean per-order decision must never
stand in for confirmed closure, which is the property `.claude/rules/30-execution.md`
names when it says a flatten is never presented as guaranteed liquidation.

## `PositionSource` is one method, not a second copy of `BrokerTruthSource`

`alphaledger.execution.reconcile.BrokerTruthSource` has three methods, and
this module needs only one of them. A fresh single-method `PositionSource`
Protocol avoids forcing every test fixture here to also implement
`open_orders` and `activities` it never calls. Nothing duplicates at a real
call site: any object that already satisfies `BrokerTruthSource` structurally
satisfies `PositionSource` too, since a `Protocol` is checked by shape.

## A conservative union is not a confirmed exposure

When `positions.positions()` raises, `still_open_symbols` is set to the union
of every target's covered symbols, and `lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON`
is added to `reasons`. That union is what the module falls back to when it has
no evidence at all, not evidence that every one of those symbols is actually
still held. A caller or a ledger entry that reads `still_open_symbols` without
also checking `reasons` for unavailability would record a claim this module
never observed, which is the same failure in the other direction from
presenting a flatten as guaranteed: it would be presenting silence as
confirmed risk instead of confirmed safety. `reasons` is what carries the
distinction; `still_open_symbols` alone does not.

## Contract

`alphaledger.execution.killswitch`, importing `money` and `require_utc` from
`alphaledger.domain`; the `alphaledger.execution.lifecycle` module itself,
for its `recover_submission` function and its `BROKER_TRUTH_UNAVAILABLE_REASON`
constant, plus `BrokerOrderLookup` and `RecoveryAction` imported by name for
type annotations, exactly the mixed style `alphaledger.execution.reconcile`
already uses on the same module; `BrokerPosition` from
`alphaledger.execution.orders`; and `KnownOrder` and `OrderReconciliation` from
`alphaledger.execution.reconcile`. None of those import back from this module,
so this adds no cycle. `alphaledger.execution.__init__` carries a docstring
and no re-exports, matching every sibling unit's own note; this unit adds
none either.

```python
DAILY_LOSS_STOP_REASON: Final[str] = "daily_loss_stop_breached"
PEAK_TO_VALLEY_KILL_SWITCH_REASON: Final[str] = "peak_to_valley_kill_switch_triggered"
POSITION_STILL_OPEN_REASON: Final[str] = "position_still_open"


@dataclass(frozen=True, slots=True)
class EquityState:
    session_start_equity: Decimal
    peak_equity: Decimal
    current_equity: Decimal
    as_of: datetime


@dataclass(frozen=True, slots=True)
class KillSwitchDecision:
    triggered: bool
    reasons: tuple[str, ...]


def evaluate_kill_switch(
    equity: EquityState,
    *,
    daily_loss_stop_fraction: Decimal,
    peak_to_valley_fraction: Decimal,
) -> KillSwitchDecision: ...


class PositionSource(Protocol):
    def positions(self) -> Sequence[BrokerPosition]: ...


@dataclass(frozen=True, slots=True)
class FlattenReport:
    targets: tuple[OrderReconciliation, ...]
    still_open_symbols: frozenset[str]
    blocks_new_entries: bool
    reasons: tuple[str, ...]


def flatten(
    order_lookup: BrokerOrderLookup,
    positions: PositionSource,
    targets: Sequence[KnownOrder],
) -> FlattenReport: ...
```

`EquityState.session_start_equity`, `.peak_equity`, and `.current_equity` are
each validated through `money`, on the same terms as every other money field
in this codebase; a `float` is rejected, never converted. `as_of` is validated
through `require_utc`. `session_start_equity` and `peak_equity` are each
divisors below and must be strictly positive; a value at or below zero raises
`ValueError` naming the field. `current_equity` has no such floor: a wiped-out
account is exactly the state this module has to be able to represent and
compare, and `current_equity` of zero does not raise. No relationship between
`peak_equity` and `current_equity` is enforced. Deriving and tracking the
running peak is entirely the caller's responsibility, see Assumptions, and a
peak that has not yet absorbed a fresh high simply yields a non-positive
drawdown fraction on that side, which never trips a threshold expressed as a
positive fraction.

`evaluate_kill_switch` computes
`daily_loss_fraction = (equity.session_start_equity - equity.current_equity) / equity.session_start_equity`
and
`peak_to_valley_observed = (equity.peak_equity - equity.current_equity) / equity.peak_equity`,
both using exact `Decimal` division. `DAILY_LOSS_STOP_REASON` is added to
`reasons` when `daily_loss_fraction >= daily_loss_stop_fraction`;
`PEAK_TO_VALLEY_KILL_SWITCH_REASON` is added when
`peak_to_valley_observed >= peak_to_valley_fraction`. Either, both, or neither
may fire in one call. `triggered` is `bool(reasons)`. `evaluate_kill_switch`
raises `ValueError` naming the argument when either threshold fraction is not
strictly greater than zero and no greater than one, mirroring the range
`alphaledger.config.RiskConfig.maximum_loss_fraction_per_new_trade` already
enforces for a fraction of this same kind.

`flatten` calls `lifecycle.recover_submission(order_lookup,
target.client_order_id, recorded_attempt=target.recorded_attempt,
local_state=target.local_state)` once per entry of `targets`, unchanged, and
records one `OrderReconciliation` per target, in the same order, in
`FlattenReport.targets`. A `RecoveryAction.BLOCK` result contributes
`decision.reason` to `FlattenReport.reasons`. A `RecoveryAction.ADOPT_EXISTING`
result contributes nothing on its own; see "What confirms a target is closed".

Separately, `flatten` reads `positions.positions()` once. If it raises,
`lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON` is added to `reasons` and
`still_open_symbols` is set to the union of every target's `covered_symbols`.
If it returns cleanly, `still_open_symbols` is the intersection of the union of
every target's `covered_symbols` with the set of symbols carrying a nonzero
`signed_quantity` in the returned positions; `POSITION_STILL_OPEN_REASON` is
added to `reasons` exactly when that intersection is non-empty.

`reasons` is the deduplicated tuple of every distinct reason that
contributed, in the order first observed, mirroring
`alphaledger.execution.reconcile.reconcile`'s own construction.
`blocks_new_entries` is `bool(reasons)`.

## Assumptions

- Computing and tracking the running peak equity, the window it spans, and the
  session-start equity snapshot are the caller's responsibility. `EquityState`
  arrives already materialized, exactly as `AccountSnapshot.equity` is
  materialized rather than derived by UNIT-013's `approve`, and exactly as
  `KnownOrder` arrives already materialized to `reconcile`.
- `lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON` is reused for both an
  unavailable `order_lookup` and an unavailable `positions` source, rather
  than a second constant for the latter, per the same simplicity precedent
  `specs/units/015-broker-reconciliation.md` recorded for itself: which
  boundary failed is the test's concern, not the report's.
- Cancelling open entry orders on a halt is a known, named gap; see Out. It is
  not this unit's to close.

## Acceptance criteria

- AC-1: a `current_equity` below `session_start_equity` by exactly
  `daily_loss_stop_fraction` triggers with `DAILY_LOSS_STOP_REASON` in
  `reasons`; tested strictly short of the fraction (no trigger), exactly at it
  (triggers), and strictly beyond it (triggers).
- AC-2: the same three-point boundary test against `peak_equity` and
  `peak_to_valley_fraction` triggers `PEAK_TO_VALLEY_KILL_SWITCH_REASON` on the
  same terms.
- AC-3: an `EquityState` that breaches both thresholds at once returns both
  reasons in one `KillSwitchDecision`, each exactly once, and `triggered` is
  `True`.
- AC-4: `current_equity` at or above `session_start_equity` and at or above
  `peak_equity`, including a `current_equity` strictly above `peak_equity`,
  never triggers either reason; `triggered` is `False` and `reasons` is empty.
- AC-5: constructing `EquityState` raises `ValueError` naming the field for a
  `session_start_equity` or `peak_equity` at or below zero; a `current_equity`
  of exactly zero does not raise.
- AC-6: `evaluate_kill_switch` raises `ValueError` naming the argument when
  `daily_loss_stop_fraction` or `peak_to_valley_fraction` is at or below zero,
  or above one.
- AC-7: `evaluate_kill_switch` called twice with an equal-by-value
  `EquityState` and equal thresholds returns two equal `KillSwitchDecision`
  values.
- AC-8: a target whose `recorded_attempt` is `None` resolves to
  `RecoveryAction.BLOCK` with `lifecycle.SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON`,
  present in `FlattenReport.reasons`, and `blocks_new_entries` is `True`.
- AC-9: at least two targets, each resolving cleanly to
  `RecoveryAction.ADOPT_EXISTING` and each covering a symbol carrying no
  nonzero-quantity position, produce one `OrderReconciliation` per target in
  the same order, an empty `still_open_symbols`, an empty `reasons`, and
  `blocks_new_entries` `False`. A defect that resolves only the first or last
  target, or silently drops one, fails this.
- AC-10: a target resolving cleanly to `RecoveryAction.ADOPT_EXISTING` at
  `OrderState.FILLED`, whose covered symbol still carries a nonzero-quantity
  position, appears in `still_open_symbols` with `POSITION_STILL_OPEN_REASON`
  in `reasons` and `blocks_new_entries` `True`. Asserting only on the target's
  own decision is not sufficient; the position check is what this AC proves.
- AC-11: a target whose closing order the broker reports as rejected
  (`BrokerOrderStatus.REJECTED`, which `lifecycle` maps to `OrderState.REJECTED`)
  still carries its covered symbol in `still_open_symbols` with
  `POSITION_STILL_OPEN_REASON`, since a rejected closing order cannot have
  closed anything the position check would otherwise clear.
- AC-12: `positions.positions()` raising, with every target's own
  `recover_submission` resolving cleanly, puts
  `lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON` in `reasons` and sets
  `still_open_symbols` to the union of every target's `covered_symbols`. The
  same scenario without the raise is AC-9's success case, and the pair proves
  the raise is what changed the outcome.
- AC-13: `order_lookup.order_by_client_id` raising for one target, with
  `positions.positions()` returning cleanly, puts
  `lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON` in `reasons` through that
  target's own `RecoveryAction.BLOCK` decision.
- AC-14: calling `flatten` twice with an equal-by-value `positions` reading and
  equal `targets` produces two equal `FlattenReport` values.
- AC-15: no targets and an empty `positions.positions()` reading together
  produce `blocks_new_entries` `False`, an empty `reasons`, and an empty
  `still_open_symbols`.
- AC-16: `RecoveryAction` has exactly two members, `ADOPT_EXISTING` and
  `BLOCK`, pinned by name. Because `flatten` calls only `recover_submission`
  and never `decide_submission`, no value in any `FlattenReport.targets[i].decision.action`
  can authorize a first submission; this is a property of the type `flatten`
  consumes, not of caller diligence, and a third member cannot be added
  without this test failing.

## Test list

- success: the daily loss stop triggers exactly at its threshold fraction and
  not strictly short of it, and strictly beyond it also triggers.
- success: the peak-to-valley kill switch triggers exactly at its threshold
  fraction, on the same three-point boundary.
- success: both thresholds breached in one `EquityState` return both reasons,
  each exactly once.
- success: at least two targets that each resolve cleanly and cover a symbol
  with no nonzero position produce an empty `still_open_symbols`, an empty
  `reasons`, and `blocks_new_entries` `False`, resolved independently in the
  input order.
- success: `evaluate_kill_switch` called twice with equal-by-value inputs
  returns equal decisions; `flatten` called twice with equal-by-value inputs
  returns equal reports.
- failure: constructing `EquityState` with a non-positive `session_start_equity`
  or `peak_equity` raises `ValueError` naming the field.
- failure: `evaluate_kill_switch` raises `ValueError` naming the argument for a
  threshold fraction at or below zero, or above one.
- failure: a target with no recorded attempt blocks with
  `submission_attempt_record_required`.
- failure: a target that resolves cleanly to `FILLED` but whose symbol still
  carries a nonzero position is reported in `still_open_symbols` with
  `position_still_open`; asserting only on the target's own decision does not
  pass.
- failure: a target whose closing order the broker rejected still carries its
  symbol in `still_open_symbols` with `position_still_open`.
- failure: `positions.positions()` raising, with every target otherwise clean,
  marks `broker_truth_unavailable` and unions every target's covered symbols
  into `still_open_symbols`; the same scenario without the raise is the
  success case above, and the pair is what proves the raise changed the
  outcome.
- failure: `order_lookup.order_by_client_id` raising for one target, with
  `positions.positions()` clean, marks `broker_truth_unavailable` through that
  target's own decision.
- restart: calling `flatten` twice with equal-by-value targets and positions,
  standing in for a retry after a restart, produces two equal reports.
- no-trade: `current_equity` at or above both `session_start_equity` and
  `peak_equity`, including a fresh high above `peak_equity`, never triggers
  either reason.
- no-trade: a `current_equity` of exactly zero does not raise `EquityState`
  construction, recording a wiped-out account rather than refusing to
  represent one.
- no-trade: no targets and an empty `positions.positions()` reading together
  produce `blocks_new_entries` `False` and empty `reasons` and
  `still_open_symbols`.
- no-trade: `RecoveryAction` has exactly two members, `ADOPT_EXISTING` and
  `BLOCK`, listed by name, so a third member, or one that could authorize a
  submission, cannot be added without a test failing.

## Verification

```bash
uv run pytest tests/execution/test_killswitch.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
