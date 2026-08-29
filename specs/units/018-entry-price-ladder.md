---
id: UNIT-018
title: Step the bounded entry price ladder
lane: execution
state: in_review
owner: pablo/codex
branch: feature/018-entry-price-ladder
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-011, UNIT-012, UNIT-013]
paths: src/alphaledger/execution/ladder.py, tests/execution/test_ladder.py
claimed_at: 2026-08-29T18:01:41Z
---

## Problem

An entry that only ever submits once at one limit price either sits at an
optimistic price and never fills, or is built to cross straight to a
conservative price and pays more than it needed to. Design section 11 step 4
requires something between those: start near the executable midpoint, step
toward the conservative natural price, and stop. Nothing today decides when to
take the next step, what the next price is allowed to be, or when to give up.
Without a mechanism that terminates by construction, a naive retry loop is
exactly the unbounded-widening hazard `.claude/rules/30-execution.md` and
design section 11's own closing sentence, "Never silently cross the risk
engine's price bound," both warn against.

## Source of truth

- `options-alpha-agent-design.md` section 11, Entry step 4, for the ladder
  itself, and its Exit subsection, which distinguishes the position's own
  ladder-shaped retry from what this unit owns; see "Entry only" below.
- `options-alpha-agent-design.md` section 12, for why position management and
  exit monitoring are a separate concern from this unit's entry-only scope.
- `.claude/rules/30-execution.md`, bullet 3, one stable client order id per
  intent and never an implicit second intent, and bullet 6, fail-closed new
  entries.
- `project-state/DECISIONS.md` D-023, the load-bearing decision for this unit.
  The id is derived from `(plan_id, quantity, limit_price)`, so a ladder step
  at a new price is a new id, a new payload, and a new approval; a retry at an
  unchanged price is the same id, which is what makes it safe to re-derive
  after a crash.
- `project-state/DECISIONS.md` D-017, on why a threshold absent from
  `config/risk.toml` and `config/session.toml` is a required parameter here,
  not an invented constant.
- `specs/000-INTAKE.md`, the UNIT-018 row and the paragraph beneath the table
  explaining why the ladder is its own unit rather than living inside
  UNIT-013.
- `specs/units/012-order-state-machine.md`, for `client_order_id` and the
  price-ladder note at its own end, "The price ladder, still deferred," which
  this unit is the deferral's resolution.
- `specs/units/013-risk-approval-token.md`, for `approve` and the precedent of
  `max_snapshot_age` as a required explicit parameter rather than a default,
  which this unit follows for its own two thresholds.
- `specs/units/017-kill-switch.md`, for the same required-parameter precedent
  from the other execution unit written against an uncommitted threshold, and
  for its own explicit exclusion of a closing-order ladder, which this unit
  does not pick up either; see "Entry only" below.
- `config/risk.toml` and `config/session.toml`, read directly. Neither commits
  a ladder step count or a ladder time budget.

## Entry only

This unit's title, its row in `specs/000-INTAKE.md`, and its one dependency on
UNIT-013 are all entry-specific: `alphaledger.risk.approval.approve` gates an
entry, not a close, and `GATE_ENTRY_LIMIT_BOUND_EXCEEDED` is named for exactly
that direction. Design section 11's Exit subsection says a stuck close falls
back to "the normal ladder," but `specs/units/017-kill-switch.md` already
decided what that means for a closing order: `flatten` does not call `approve`
at all, because a close needs no risk approval, only the id and lifecycle
machinery UNIT-012 already gives it, and a new price still yields a new id by
the same D-023 mechanism with no separate ladder abstraction required. This
unit does not build a second, closing-order version of itself. If a bounded
retry specifically for a closing order is ever found to need more than that,
it is a new unit, not an extension of this one, because it would not call
`approve` and would therefore share none of this module's actual work.

## Scope

In:

- `step_ladder`, one pure decision per requested rung: given the full bounded
  sequence of candidate limit prices, the rung the caller is asking about, and
  the ladder's own clock and budget, either derive that rung's id, payload,
  and a fresh risk approval, or report that the ladder is exhausted and why.
- `LadderBudget`, the two required thresholds design section 11 step 4 needs
  and `config/` does not commit: how many rungs the ladder may hold, and how
  long it may run before it must stop regardless of rungs remaining.
- Refusing, loudly, a caller-supplied price ladder that is empty, longer than
  the budget allows, not strictly increasing, or containing a rung above
  `plan.entry_limit_bound`. Every one of these is a construction error, not a
  market condition, so every one raises rather than being recorded as a
  refused decision.

Out:

- Choosing the actual rung prices from bid, ask, midpoint, and natural price.
  Design section 5's and section 8's economics live with whichever unit
  enumerates the structure and its quotes (UNIT-014); this unit consumes an
  already-built, already-ordered sequence of prices exactly as
  `specs/units/013-risk-approval-token.md`'s `AccountSnapshot.equity` and
  `specs/units/017-kill-switch.md`'s `EquityState` arrive already materialized
  rather than derived here. No unit intake today names the function that
  produces bid, midpoint, and natural prices for a plan; that is a real gap,
  the same shape `specs/000-INTAKE.md` already records for UNIT-027 and
  UNIT-028, and does not block this unit, which is fully specified, claimable,
  and testable against fixture price sequences without that caller existing
  yet, exactly as UNIT-013 and UNIT-017 were each written and merged before a
  real caller invoked them.
- A closing order's bounded retry. See "Entry only" above.
- Transport, submission, and cancellation. This module performs no I/O. A
  caller submits the payload this unit returns and cancels the prior rung's
  working order before asking for the next one; this module holds no order
  state across calls and does not observe whether a cancel actually happened.
- Deriving the client order id and the eleven-state machine (UNIT-012). This
  unit calls `client_order_id` unchanged and does not redefine it.
- Building the order payload and computing its hash (UNIT-011). This unit
  calls `build_mleg_order` unchanged.
- The risk gates themselves, sizing, and the account snapshot (UNIT-013). This
  unit calls `approve` unchanged and does not re-implement or duplicate any of
  its gates. A rung whose `approve` call refuses for a reason unrelated to
  price, for example the concurrent-position cap, is still a returned step;
  see AC-14. This unit's own exhaustion reasons are about the ladder running
  out of rungs or time, never about a risk gate.
- The scheduled reconcile loop and orphan-position recovery (UNIT-015).
- The ledger (UNIT-016). Recording a step, a refusal, or an exhausted ladder
  is a ledger write; this module returns values for a caller to record.
- The kill switch and emergency flatten (UNIT-017).
- The session and arm state machine, and the decision to start a ladder at
  all, which belongs to the orchestrator, exactly as UNIT-012, UNIT-013, and
  UNIT-017 each already draw this same line for their own scope.

## Why the two thresholds are parameters, not constants

Design section 11 step 4 requires "a small bounded ladder" and a cutoff at
"the final limit or time budget," but gives neither number, and neither
`config/risk.toml` nor `config/session.toml` commits one today; both were read
directly to confirm this. Per D-017 a threshold that is not committed and
hashed cannot be invented in code, so `LadderBudget.max_steps` and
`LadderBudget.time_budget` are required constructor arguments with no default,
exactly the shape `specs/units/013-risk-approval-token.md` chose for
`max_snapshot_age` and `specs/units/017-kill-switch.md` chose for
`daily_loss_stop_fraction` and `peak_to_valley_fraction`. The natural
long-term home for both is two new fields on `RiskConfig` or `SessionConfig`,
hashed into the run manifest; that is a change to UNIT-004's files and belongs
to whoever wires a real caller, not to this unit's declared paths.

## Why the price sequence is validated, not computed

`price_ladder` arrives as a caller-supplied, already-ordered sequence of
candidate limit prices. This unit does not compute it, for the same reason
`approve` does not compute `AccountSnapshot`: the inputs this unit needs to
decide safely, entry_limit_bound aside, come from market quotes this module
has no way to observe, since it performs no I/O. What this unit does own is
refusing a malformed sequence before it is ever used, on every call, since the
module holds no state between calls and cannot assume a sequence validated on
a previous call is the same one supplied now:

- empty, or longer than `budget.max_steps`;
- not strictly increasing, tested rung to rung. Two equal adjacent rungs would
  derive the identical `client_order_id` at two different `step_index`
  values, since the id is a function of price and not of index, which would
  make one ladder step silently indistinguishable from another;
- any rung strictly greater than `plan.entry_limit_bound`. A rung exactly
  equal to the bound is accepted, mirroring
  `specs/units/013-risk-approval-token.md` AC-3's own equal-is-not-refused
  boundary for the same field. This check makes "never silently cross the
  risk engine's price bound" true for every rung this module ever constructs.
  `approve`'s own `GATE_ENTRY_LIMIT_BOUND_EXCEEDED` is a second, independent
  enforcement of the identical bound; it is not a fallback this unit relies
  on, since nothing inside `step_ladder` can reach `approve` with an
  over-bound price in the first place. A caller that calls
  `alphaledger.risk.approval.approve` directly, outside `step_ladder`
  entirely, still cannot obtain an over-bound approval, because that gate
  belongs to `approve` regardless of whether this module was ever involved.

Every one of these is a caller or construction error, never a live market or
account condition, so every one raises `ValueError` rather than producing a
refused decision. This is the same distinction
`specs/units/013-risk-approval-token.md` draws between a structurally invalid
payload, which raises, and a payload that is readable but risk-relevant, which
gates; see that intake's "The payload is rebuilt, not trusted."

## Same-price idempotency, preserved

Because `client_order_id` is a pure function of `(plan_id, quantity,
limit_price)`, calling `step_ladder` twice for the same `step_index` against
the same `price_ladder`, with the same clock and account snapshot, derives the
identical id, the identical payload, and, since `approve` is itself
deterministic, the identical `RiskApproval`. A caller recovering after a crash
between deriving a rung and recording the attempt re-derives exactly what it
already had rather than creating a second intent, the same guarantee
`specs/units/012-order-state-machine.md` AC-1 and
`specs/units/013-risk-approval-token.md` AC-1 each already give their own
callers. A ladder step at a *different* price is a different id by the same
construction, which is D-023's whole point: stepping the ladder is not a
modification of a working order, it is cancel, then a new intent under a new
id, approved fresh.

## Contract

`alphaledger.execution.ladder`, importing `money` and `require_utc` from
`alphaledger.domain`; `StructurePlan` and `RiskApproval` from
`alphaledger.domain` by name for type annotations; `client_order_id` from
`alphaledger.execution.lifecycle`; `build_mleg_order` from
`alphaledger.execution.orders`; and `AccountSnapshot`, `SizingMode`, `approve`
from `alphaledger.risk.approval`, plus `FrozenConfig` from `alphaledger.config`
for a type annotation. None of those import back from this module, so this
adds no cycle. `alphaledger/execution/__init__.py` keeps its docstring and no
re-exports, matching every sibling unit's own note; this unit adds none
either.

```python
LADDER_STEPS_EXHAUSTED_REASON: Final[str] = "ladder_steps_exhausted"
LADDER_TIME_BUDGET_EXCEEDED_REASON: Final[str] = "ladder_time_budget_exceeded"


@dataclass(frozen=True, slots=True)
class LadderBudget:
    max_steps: int
    time_budget: timedelta


@dataclass(frozen=True, slots=True)
class LadderStep:
    step_index: int
    limit_price: Decimal
    client_order_id: str
    payload: Mapping[str, object]
    approval: RiskApproval


@dataclass(frozen=True, slots=True)
class LadderDecision:
    step: LadderStep | None
    reasons: tuple[str, ...]


def step_ladder(
    plan: StructurePlan,
    quantity: int,
    price_ladder: Sequence[Decimal],
    step_index: int,
    ladder_started_at: datetime,
    now: datetime,
    budget: LadderBudget,
    snapshot: AccountSnapshot,
    frozen_config: FrozenConfig,
    mode: SizingMode,
    expires_at: datetime,
    max_snapshot_age: timedelta,
) -> LadderDecision: ...
```

`LadderBudget.__post_init__` raises `ValueError` naming the field for
`max_steps` at or below zero, or for `time_budget` not a positive `timedelta`.
`LadderBudget` is validated once at construction, the same way
`AccountSnapshot` and `EquityState` validate their own fields rather than
deferring to the function that later consumes them.

`LadderStep` and `LadderDecision` carry no validation of their own; both are
constructed only internally by `step_ladder` after every input has already
been checked, the same as `OrderReconciliation` and `SubmissionDecision` in
`alphaledger.execution.lifecycle` and `alphaledger.execution.reconcile`.

`step_ladder` proceeds in this order:

1. `now` and `ladder_started_at` are each passed through `require_utc`.
   `ladder_started_at` strictly after `now` raises `ValueError`; observing a
   ladder that started after the current instant is always wrong and needs no
   threshold, the same reasoning D-014 already applies to
   `first_seen_time`/`source_time` and
   `specs/units/013-risk-approval-token.md` applies to
   `GATE_SNAPSHOT_IN_FUTURE`.
2. `step_index` not a non-negative `int` (booleans excluded) raises
   `ValueError` naming the field.
3. `price_ladder` is validated as a whole, per "Why the price sequence is
   validated, not computed" above, raising `ValueError` on the first
   violation found. This happens before either exhaustion check below, so an
   invalid sequence always raises even when `step_index` alone would already
   indicate the ladder is exhausted.
4. Two independent exhaustion checks are evaluated, both, either, or neither
   contributing a reason to one deduplicated `reasons` tuple, mirroring how
   `specs/units/017-kill-switch.md` `evaluate_kill_switch` collects both of
   its own reasons in one pass rather than returning after the first:
   `now - ladder_started_at >= budget.time_budget` contributes
   `LADDER_TIME_BUDGET_EXCEEDED_REASON`; `step_index >= len(price_ladder)`
   contributes `LADDER_STEPS_EXHAUSTED_REASON`.
5. If `reasons` is non-empty, `step_ladder` returns
   `LadderDecision(step=None, reasons=reasons)` and computes nothing further;
   no id, payload, or approval is derived for an exhausted ladder.
6. Otherwise `limit_price = price_ladder[step_index]`;
   `cid = client_order_id(plan.plan_id, quantity, limit_price)`;
   `payload = build_mleg_order(plan, quantity, limit_price, cid)`;
   `approval = approve(plan, payload, snapshot, frozen_config, mode,
   expires_at, now, max_snapshot_age)`. `step_ladder` returns
   `LadderDecision(step=LadderStep(step_index, limit_price, cid, payload,
   approval), reasons=())`.

A rung whose `approval.approved` is `False` is still returned as a `LadderStep`
with an empty `reasons` tuple on the `LadderDecision`; the risk refusal lives
in `approval.failed_gates`, never folded into this module's own `reasons`,
which name only ladder-mechanical exhaustion. Conflating the two would make a
caller unable to tell "this rung's price was fine but sizing was refused"
from "there is no rung left to try," which need different responses: the
first is a reason to stop this plan without necessarily retrying at another
price, the second is ordinary ladder exhaustion.

`quantity` is fixed for the whole ladder; only `limit_price` changes between
rungs. Sizing `quantity` itself, through
`alphaledger.risk.approval.max_approved_quantity`, happens once before a
ladder starts and is a caller responsibility, not this unit's.

## Assumptions

- The caller advances `step_index` and cancels the previous rung's working
  order before requesting the next one. This module holds no state between
  calls and does not verify that sequencing, the same boundary
  `specs/units/015-broker-reconciliation.md` and
  `specs/units/017-kill-switch.md` draw around their own callers' obligations.
- Only debit verticals are in the frozen strategy allowlist today
  (`config/session.toml`'s `strategy_allowlist`), so a ladder that only ever
  increases price toward a ceiling, `plan.entry_limit_bound`, is complete for
  every structure this system may currently trade. A credit structure's
  ladder would need to decrease price toward a floor instead, and is out of
  scope until the allowlist changes to include one.
- `price_ladder`'s tick size and rounding are the caller's concern. Each rung
  arrives as an already-valid, already-quote-derived `Decimal`; this unit
  checks ordering and the bound, and invents no rounding rule of its own.

## Acceptance criteria

- AC-1: `step_ladder` called twice with identical arguments, including an
  identical `now` and `snapshot`, returns two `LadderDecision` values equal in
  every field, including `LadderStep.client_order_id` and
  `LadderStep.approval.approval_id`.
- AC-2: two calls at two different valid `step_index` values against the same
  `price_ladder`, where the two rungs differ, produce different
  `client_order_id` and different `approval.approval_id` values.
- AC-3: a `price_ladder` containing a rung strictly greater than
  `plan.entry_limit_bound` raises `ValueError`; a rung exactly equal to
  `entry_limit_bound` is accepted and does not raise on this account.
- AC-4: a `price_ladder` with two equal adjacent rungs raises `ValueError`.
- AC-5: a `price_ladder` longer than `budget.max_steps` raises `ValueError`.
- AC-6: constructing `LadderBudget` raises `ValueError` naming the field for a
  `max_steps` at or below zero, and for a `time_budget` at or below
  `timedelta(0)`.
- AC-7: `step_ladder` raises `ValueError` naming `step_index` when it is
  negative.
- AC-8: `step_ladder` raises `ValueError` when `ladder_started_at` is strictly
  after `now`.
- AC-9: `step_index` at exactly `len(price_ladder)`, and strictly beyond it,
  each return `LadderDecision(step=None,
  reasons=(LADDER_STEPS_EXHAUSTED_REASON,))`; `step_index` at
  `len(price_ladder) - 1`, the last valid rung, still returns a non-`None`
  step.
- AC-10: `now - ladder_started_at` at exactly `budget.time_budget`, and
  strictly beyond it, each return `LadderDecision(step=None,
  reasons=(LADDER_TIME_BUDGET_EXCEEDED_REASON,))` at `step_index = 0`; strictly
  short of the budget does not.
- AC-11: an input where both the time budget is exceeded and `step_index` is
  exhausted at once returns both reasons in one `LadderDecision`, each exactly
  once.
- AC-12: for every input, `step_ladder` returns a `LadderDecision` for which
  `(decision.step is None) == bool(decision.reasons)`, checked as an explicit
  assertion against the return value of each of the AC-9, AC-10, AC-11, and
  AC-14 scenarios in turn, rather than asserted once on a hand-built
  `LadderDecision` that was never returned by the function.
- AC-13: when every check passes, `step.approval` equals what calling
  `alphaledger.risk.approval.approve` independently produces from the same
  rebuilt payload, snapshot, frozen config, mode, expiry, current `now`, and
  `max_snapshot_age`.
- AC-14: an `approve` call that returns `approved=False` for a reason
  unrelated to price, for example `GATE_CONCURRENT_POSITION_LIMIT`, still
  yields a `LadderDecision` with a non-`None` `step` and an empty `reasons`;
  the refusal is visible only through `step.approval.failed_gates`.
- AC-15: an invalid `price_ladder`, per AC-3 or AC-4, raises even when
  `step_index` alone would already indicate the ladder is exhausted, proving
  validation is not skipped by an early exhaustion return.

## Test list

- success: two calls with identical arguments return equal `LadderDecision`
  values in every field.
- success: two calls at different valid step indices against rungs of
  different prices produce different ids and different approval ids.
- success: a rung exactly equal to `plan.entry_limit_bound` is accepted.
- success: the last valid rung, `step_index == len(price_ladder) - 1`, still
  returns a step.
- success: `step.approval` matches an independently computed `approve` call
  over the same rebuilt inputs.
- failure: a rung strictly above `plan.entry_limit_bound` raises `ValueError`.
- failure: two equal adjacent rungs raise `ValueError`.
- failure: a `price_ladder` longer than `budget.max_steps` raises
  `ValueError`.
- failure: constructing `LadderBudget` with a non-positive `max_steps` or a
  non-positive `time_budget` raises `ValueError` naming the field.
- failure: a negative `step_index` raises `ValueError`.
- failure: `ladder_started_at` strictly after `now` raises `ValueError`.
- failure: an invalid `price_ladder` raises even when `step_index` already
  indicates exhaustion, proving the check is not skipped.
- restart: `step_ladder` invoked in a subprocess from the same plan,
  quantity, price ladder, step index, clock, snapshot, frozen config, mode,
  expiry, and `max_snapshot_age` produces the identical `client_order_id` and
  `approval.approval_id` as the original process, mirroring
  `specs/units/012-order-state-machine.md` and
  `specs/units/013-risk-approval-token.md`'s own restart tests.
- restart: a step recomputed after a simulated crash, same `step_index` and
  same inputs, reproduces the identical id rather than advancing to a new
  one, proving same-price idempotency.
- no-trade: `step_index` at exactly `len(price_ladder)`, and strictly beyond
  it, both return an exhausted decision with `LADDER_STEPS_EXHAUSTED_REASON`
  and no step.
- no-trade: elapsed time at exactly `budget.time_budget`, and strictly beyond
  it, both return an exhausted decision with
  `LADDER_TIME_BUDGET_EXCEEDED_REASON` and no step, at `step_index = 0`.
- no-trade: both exhaustion conditions at once return both reasons together,
  each exactly once.
- no-trade: a returned step whose `approval.approved` is `False` for a
  non-price reason is not itself treated as ladder exhaustion; `reasons` on
  the `LadderDecision` stays empty.

## Verification

```bash
uv run pytest tests/execution/test_ladder.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
