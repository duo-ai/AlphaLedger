---
id: UNIT-013
title: Produce a risk approval token bound to the order payload
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-004, UNIT-011]
paths: src/alphaledger/risk/**, tests/risk/**
claimed_at: 2026-08-29T11:40:32Z
---

## Problem

A `StructurePlan` and a built order payload exist, but nothing decides whether
submitting that exact payload is safe, and nothing produces the `RiskApproval`
the frozen domain record already reserves fields for. Without a deterministic
check bound to the exact payload, the exact account state, and the exact
frozen configuration, an approval would be a rubber stamp: it could authorise
a payload nobody re-verified, at a size nobody bounded, under a configuration
that had since changed.

## Source of truth

- `options-alpha-agent-design.md` section 10 (Risk policy) for the sizing
  formula, the hard rules, and the approval-binding paragraph.
- `options-alpha-agent-design.md` section 8 (Exact payoff algebra) for what
  `exact_max_loss` and a debit vertical's price bound actually mean in dollars.
- `options-alpha-agent-design.md` section 9 (Liquidity and data-quality gates),
  to the extent it is implementable here; most of it is not, and the reasons
  are recorded in Scope below.
- `.claude/rules/30-execution.md`, bullet 2, for the two-part submission gate,
  and bullet 6, for the fail-closed reasons a new entry must refuse on.
- `project-state/DECISIONS.md` D-023, which fixes the order of operations this
  unit sits inside: id, then payload, then payload hash, then approval.
- `project-state/DECISIONS.md` D-014, on why a leg schema is not assumed here
  beyond what UNIT-011 already fixed for the order payload.
- `project-state/DECISIONS.md` D-017, on why a threshold this unit does not
  find in `config/` is not invented in code.
- `config/risk.toml`, the actual frozen values this unit reads. Do not use
  `options-alpha-agent-design.md` section 10's table values directly; that
  table states initial engineering defaults, and `config/risk.toml` is what is
  actually frozen today, per D-017.

## Scope

In:

- A frozen `AccountSnapshot` record this unit defines, carrying the equity,
  open position count, the `frozen_config_hash` of the configuration the
  snapshot was taken under, and the snapshot's own timestamp. Nothing existing
  defines this type; `grep -rln "AccountSnapshot"` before writing this intake
  found only this file.
- `account_snapshot_hash`, a canonical hash over that snapshot, reusing
  `alphaledger.execution.orders.canonical_bytes` rather than a second
  serialisation scheme.
- `max_approved_quantity`, a pure sizing function over the plan's exact max
  loss, the account equity, and the frozen risk caps.
- `approve`, which takes a plan, an already-built order payload, an account
  snapshot, the frozen configuration, and an explicit expiry, and returns a
  `RiskApproval` bound to the exact payload and the exact snapshot. It
  recomputes `order_payload_hash` itself; it never accepts an externally
  computed hash on faith. It reuses `RiskApproval`, `StructurePlan`, `money`,
  and `require_utc` from `alphaledger.domain`, and `RiskConfig` and
  `FrozenConfig` from `alphaledger.config`, all merged and none redefined here.
- `is_expired`, the read-side counterpart: a stale approval is refused, not
  renewed, and this is what a caller checks before using one.
- The gates this unit can actually compute from data that exists today: the
  payload's limit price against the plan's approved price bound, the payload's
  quantity against the frozen sizing cap, a balanced-legs check on the payload,
  the concurrent-position cap, and a check that the snapshot's own recorded
  configuration hash matches the configuration being used to evaluate it.
  Every gate is a named module constant, listed in the Contract.
- The one-contract smoke-test cap, selected by an explicit `SizingMode`, never
  by a `bool`. See "Why not a bool" below.

Out:

- Transport and paper-endpoint assertion (UNIT-010). This module performs no
  I/O and reaches the network never.
- Building the order payload and schema mapping (UNIT-011). This unit consumes
  the payload `build_mleg_order` produces; it does not construct one.
- The order state machine and `client_order_id` derivation (UNIT-012). This
  unit does not derive an id and does not decide submission timing.
- Enumerating real chains, computing exact payoffs, and validating spread
  construction, including the `D<=0`, `D>=W`, inconsistent expiration or
  underlying, and naked-short-leg checks design section 8 assigns to
  candidate construction (UNIT-014). This unit's balanced-legs gate, described
  below, is a payload-level defence in addition to that check, not a
  replacement for it.
- The scheduled reconcile loop, orphan-position recovery, and the account
  snapshot's own construction from broker truth (UNIT-015). This unit consumes
  an `AccountSnapshot`; it does not assemble one from positions or activities.
- The ledger (UNIT-016). Recording an approval, a refusal, or a `no_trade` is
  the ledger's job, not this one's.
- The kill switch and emergency flatten (UNIT-017), which is exactly what the
  design's peak-to-valley equity trigger belongs to, per its own title.
- The session and arm state machine, disarmed through halted, that design
  section 11's diagram shows. UNIT-012 already drew this line for the order
  lifecycle and the same reasoning applies here: that machine belongs to the
  orchestrator. `RiskConfig.require_human_paper_arm` is a frozen policy
  declaration that a human arm is mandatory; it is forced `True` by
  `RiskConfig.__post_init__` and cannot be disabled. This unit does not check
  an arm token against it, because no such token exists yet anywhere in the
  repository, and inventing one here would be building the orchestrator's
  state machine inside the risk module.
- The bounded entry price ladder from design section 11 step 4, owned by
  UNIT-018, which depends on this unit and on UNIT-012 for exactly the reason
  given there: a ladder step changes the limit price and therefore the
  payload and its hash, so each step is a new `approve` call against a new
  payload, and the ladder itself is a bounded loop that calls this unit
  repeatedly rather than something implemented inside it.
- Five limits design section 10's table names, which this unit does not
  assert because no frozen threshold for them exists in `config/risk.toml`
  today: total open defined risk, sector open risk, positions per underlying,
  and the daily realized-plus-unrealized loss stop have no field in
  `RiskConfig` at all, and the peak-to-valley equity kill switch is UNIT-017's
  by title. Per D-017, a threshold that is not committed and hashed is not
  something this unit may invent in code; extending `risk.toml` with these
  fields is a separate, future change to a file this unit's declared paths do
  not include.
- Design section 9's liquidity and data-quality gates: crossed or stale
  quotes, missing contract metadata or multiplier, missing Greeks, bid/ask
  width, and displayed size. None of these has a field on `StructurePlan` or a
  frozen threshold in `config/`, and per AGENTS.md's engineering boundaries,
  structure code is what enumerates real chains, so a candidate that fails
  one of these gates is exactly a candidate UNIT-014 should never have
  produced. This unit approves or refuses the plan and payload it is given; it
  does not re-inspect the market data behind them.

## Why not a bool

`RiskConfig` carries both `max_contracts_per_structure` and
`smoke_test_max_contracts`, and the caller has to say which cap applies to a
given `approve` call. A `bool` is the shape this repository has rejected
twice already for exactly this kind of safety-relevant selector: D-021 records
why no `paper: bool` exists anywhere, and UNIT-012's first review round
blocked on a submission decision gated by a bare `bool` that a crash could
silently leave at its default. `SizingMode` is a two-member `StrEnum`,
`standard` and `smoke_test`, so a caller states its intent by name and an
unset or wrong-typed value is a type error, not a silent default.

## `start_at_half_risk` is not a multiplier

`config/risk.toml` sets `maximum_loss_fraction_per_new_trade` to `0.00375` and
`maximum_concurrent_positions` to `2`, which are already half of design
section 10's initial defaults of `0.75%` and `4`. `start_at_half_risk = true`
records that this halving was a deliberate choice, per the build plan's
"half risk until the first complete round trip succeeds." It is a disclosure
field, not an input to arithmetic. No code in this unit reads
`start_at_half_risk` to scale anything; the committed fractions and counts are
already the values to enforce.

## Two money conventions, not one

Design section 8 gives maximum loss for a debit vertical as `100D` dollars,
where `D` is the net debit in points and `100` is the option contract
multiplier. `StructurePlan.exact_max_loss` is that dollar figure, already
multiplier-scaled, for one spread, one contract of quantity. The total risk
for an approved quantity is `exact_max_loss * quantity`, and
`max_approved_quantity` below divides equity fraction by `exact_max_loss` for
exactly this reason. `StructurePlan.entry_limit_bound` and the payload's
`limit_price` are a different quantity: a per-share price bound in the same
points convention Alpaca's option order accepts, not multiplier-scaled.
Confusing the two would size a position up to a hundred times too large in
the risk-increasing direction. UNIT-014, which will produce
`entry_limit_bound` and `exact_max_loss` together, inherits the obligation to
keep them on these two conventions; this unit only consumes them, and states
the convention rather than guessing it silently.

## Contract

`alphaledger.risk.approval`, importing from `alphaledger.domain`,
`alphaledger.config`, and `alphaledger.execution.orders`. None of those import
back from `alphaledger.risk`, so this adds no cycle.
`alphaledger/risk/__init__.py` carries a docstring and no re-exports,
matching `alphaledger/execution/__init__.py`.

```python
class SizingMode(StrEnum):
    STANDARD = "standard"
    SMOKE_TEST = "smoke_test"

GATE_ENTRY_LIMIT_BOUND_EXCEEDED: Final = "entry_limit_bound_exceeded"
GATE_QUANTITY_EXCEEDS_APPROVED_CAP: Final = "quantity_exceeds_approved_cap"
GATE_UNBALANCED_LEGS: Final = "unbalanced_legs"
GATE_CONCURRENT_POSITION_LIMIT: Final = "concurrent_position_limit_reached"
GATE_CONFIG_HASH_MISMATCH: Final = "config_hash_mismatch"

@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: Decimal
    open_position_count: int
    frozen_config_hash: str
    snapshot_time: datetime

def account_snapshot_hash(snapshot: AccountSnapshot) -> str: ...

def max_approved_quantity(
    plan: StructurePlan,
    equity: Decimal,
    risk_config: RiskConfig,
    mode: SizingMode,
) -> int: ...

def approve(
    plan: StructurePlan,
    payload: Mapping[str, object],
    snapshot: AccountSnapshot,
    frozen_config: FrozenConfig,
    mode: SizingMode,
    expires_at: datetime,
    now: datetime,
) -> RiskApproval: ...

def is_expired(approval: RiskApproval, now: datetime) -> bool: ...
```

`AccountSnapshot.equity` is validated through `money()`, on the same terms as
every other money field in this codebase; a `float` is rejected, never
converted. `snapshot_time` is validated through `require_utc`.
`open_position_count` is a non-negative whole number.

`AccountSnapshot.frozen_config_hash` exists to close a gap in the frozen
domain contract. Rule bullet 2 requires a risk approval "bound to the
canonical order payload and frozen config hashes", but `RiskApproval`, frozen
by UNIT-001, has exactly one hash field for account state,
`account_snapshot_hash`, and none for configuration. Rather than amend a
frozen contract for a field the design already implies belongs to the account
snapshot's own context, this unit folds the active `frozen_config_hash` into
what `AccountSnapshot` carries and therefore into what `account_snapshot_hash`
hashes. `approve` then checks that the folded-in hash agrees with the
`FrozenConfig` it is actually evaluating against, refusing under
`GATE_CONFIG_HASH_MISMATCH` when they disagree. This is the same shape as
design section 15's row for a risk or config hash changing after arm: disarm
and require an explicit re-check, expressed here as a refusal rather than a
session-level disarm, since the session machine is out of scope above.

`approve` takes the built payload itself, `Mapping[str, object]`, and not a
caller-supplied `order_payload_hash` string. UNIT-011's own intake states that
`order_payload_hash` "exists in the merged contracts with nothing producing
it, so this unit is its producer. If a later unit invents a second scheme the
binding becomes decorative." Accepting a hash on faith would let a caller bind
an approval to a payload it never actually re-hashed; recomputing it here from
the real payload, through the one producer that exists, is what keeps the
binding real. `approve` extracts `qty`, `limit_price`, and `legs` from the
payload directly, raising `ValueError` naming the field if one is missing or
malformed, rather than a bare `KeyError` or `TypeError`; it does not accept a
separate `quantity` or `limit_price` argument that could disagree with what
the payload actually carries.

`approve` raises `ValueError` for a caller-contract violation: `expires_at` at
or before `now`, or a plan whose `exact_max_loss` is not strictly positive,
which the sizing division below cannot proceed from. It never raises for a
gate a market or account condition trips; those produce a refused
`RiskApproval` instead, with the tripped gates named in `failed_gates`.

`RiskApproval.__post_init__`, already merged, refuses to construct an
approval where `approved` is `True` and `failed_gates` is non-empty, or where
`approved` is `False` and `failed_gates` is empty. An unexplained refusal is
therefore impossible by construction; this unit relies on that existing
guarantee rather than re-implementing it.

The balanced-legs gate sums the payload's per-leg `ratio_qty` by `side`; equal
buy-side and sell-side totals, with the payload already constrained to two to
four legs by `build_mleg_order`, is necessary for a bounded structure but not
sufficient. It catches a payload that reached this unit with a leg dropped or
duplicated. It does not prove the structure is a valid debit vertical; that
proof is design section 8's `D<=0`/`D>=W`/naked-short check, performed when
the structure is built, per UNIT-014 above.

`max_approved_quantity` computes
`floor(equity * risk_config.maximum_loss_fraction_per_new_trade / plan.exact_max_loss)`,
rounding toward zero so the fraction is never exceeded by rounding, then caps
that at `risk_config.max_contracts_per_structure` in `STANDARD` mode or
`risk_config.smoke_test_max_contracts` in `SMOKE_TEST` mode. A result of zero,
from equity too small relative to the plan's own max loss, is zero contracts:
a caller sees this before ever building a payload, and this is where the
sizing half of a `no_trade` decision actually happens, not inside `approve`.

`approval_id` is derived, not random: a SHA-256 digest, base64-urlsafe
encoded, over the canonical bytes of
`(plan.plan_id, the payload's own quantity, the recomputed order_payload_hash, account_snapshot_hash, mode, expires_at, approved, failed_gates)`,
using `canonical_bytes` again rather than a second scheme. The same inputs
produce the same id in a separate process, matching `client_order_id`'s
determinism in `alphaledger.execution.lifecycle`.

## Acceptance criteria

- AC-1: `approve` called twice with identical arguments, in separate
  processes, produces an identical `RiskApproval` in every field, including
  `approval_id`.
- AC-2: `account_snapshot_hash` changes when any single `AccountSnapshot`
  field changes, tested field by field: `equity`, `open_position_count`,
  `frozen_config_hash`, `snapshot_time`. A test that mutates one example field
  cannot tell a complete hash from one that silently drops a field.
- AC-3: a payload whose `limit_price` exceeds `plan.entry_limit_bound` is
  refused with `GATE_ENTRY_LIMIT_BOUND_EXCEEDED` in `failed_gates`, and
  `limit_price` equal to the bound is not refused on this gate.
- AC-4: a payload whose quantity exceeds `max_approved_quantity` for the same
  plan, snapshot, and mode is refused with `GATE_QUANTITY_EXCEEDS_APPROVED_CAP`.
- AC-5: a payload whose summed buy-side and sell-side `ratio_qty` disagree is
  refused with `GATE_UNBALANCED_LEGS`.
- AC-6: a snapshot whose `open_position_count` is at or above
  `risk_config.maximum_concurrent_positions` is refused with
  `GATE_CONCURRENT_POSITION_LIMIT`.
- AC-7: a snapshot whose `frozen_config_hash` does not equal the evaluated
  `FrozenConfig.frozen_config_hash` is refused with `GATE_CONFIG_HASH_MISMATCH`.
- AC-8: when every gate above passes, `approved` is `True`, `failed_gates` is
  empty, and both `account_snapshot_hash` and `order_payload_hash` on the
  returned approval equal those functions called independently on the same
  snapshot and payload.
- AC-9: `max_approved_quantity` returns zero when
  `equity * maximum_loss_fraction_per_new_trade` is less than one plan's
  `exact_max_loss`, and otherwise returns
  `min(floor(equity * fraction / exact_max_loss), cap)` with `cap` selected by
  `mode`; a test exercises both modes and shows `SMOKE_TEST` capping a
  quantity `STANDARD` would allow.
- AC-10: `is_expired(approval, now)` is `True` exactly when
  `now >= approval.expires_at`, tested strictly before, at, and strictly after
  the boundary.
- AC-11: `approve` raises `ValueError` rather than returning any `RiskApproval`
  when `expires_at` is at or before `now`, and when `plan.exact_max_loss` is
  not strictly positive.
- AC-12: `approval_id` is reproducible from the same inputs in a subprocess,
  and changes if any one of `plan_id`, quantity, `order_payload_hash`,
  `account_snapshot_hash`, `mode`, `expires_at`, `approved`, or `failed_gates`
  differs, tested one field at a time.

## Test list

- success: every gate passes and `approve` returns an approved token whose
  bound hashes match independent recomputation.
- success: `max_approved_quantity` in `STANDARD` mode returns the expected
  floor-divided, capped quantity for a plan and an equity value chosen so the
  risk-sized quantity is below the frozen cap.
- success: `max_approved_quantity` in `SMOKE_TEST` mode caps at
  `smoke_test_max_contracts` even when the risk-sized quantity and the
  standard cap would both allow more.
- success: `is_expired` agrees at, before, and after the exact expiry instant.
- failure: `approve` raises `ValueError` when `expires_at` is at or before
  `now`.
- failure: `approve` raises `ValueError` when `plan.exact_max_loss` is zero or
  negative, naming the field, rather than dividing by it.
- failure: `approve` raises `ValueError`, not `KeyError` or `TypeError`, when
  the payload is missing `qty`, `limit_price`, or `legs`.
- failure: `account_snapshot_hash` changes under each single-field mutation
  from AC-2, parameterised rather than a single example.
- failure: `approval_id` changes under each single-field mutation from AC-12,
  parameterised rather than a single example.
- restart: `approve` run in a subprocess from the same plan, payload,
  snapshot, frozen config, mode, and expiry produces the identical
  `approval_id`, `account_snapshot_hash`, and `order_payload_hash` as the
  original process.
- restart: `is_expired` evaluated in a subprocess on a serialised `RiskApproval`
  and the same boundary `now` agrees with the original process.
- no-trade: `max_approved_quantity` returns zero when equity is too small
  relative to `plan.exact_max_loss`, and the assertion is on the zero return,
  since no payload exists yet at this stage for a `no_trade` to be logged
  against.
- no-trade: `approve` refuses with `GATE_ENTRY_LIMIT_BOUND_EXCEEDED`,
  `GATE_QUANTITY_EXCEEDS_APPROVED_CAP`, `GATE_UNBALANCED_LEGS`,
  `GATE_CONCURRENT_POSITION_LIMIT`, and `GATE_CONFIG_HASH_MISMATCH` all at
  once when every condition holds simultaneously, and every one of the five
  names appears in `failed_gates`, none silently dropped by a gate that only
  records the first failure it finds.
- no-trade: `approve` in `SMOKE_TEST` mode refuses a payload quantity that
  `STANDARD` mode would have approved, because the smoke cap applies.

## Verification

```bash
uv run pytest tests/risk -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
