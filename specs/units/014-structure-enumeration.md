---
id: UNIT-014
title: Enumerate real chains and compute exact payoffs
lane: execution
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-011]
paths: src/alphaledger/structure/**, tests/structure/**
---

## Problem

The forecast pipeline can say a symbol should go long or short, but nothing
turns that into a specific options position. The only ways to pick strikes
without this unit are asking a language model, which `AGENTS.md` forbids
outright, or hardcoding a static guess disconnected from the real chain, which
produces a payoff nobody can verify against actual quotes. Nothing today reads
a real chain, screens it against the liquidity and data-quality floor design
section 9 requires, or computes the exact bounded loss and profit design
section 8 defines, so no `StructurePlan` can be produced at all, and every
downstream unit that consumes one, UNIT-011's order adapter among them, has
nothing to consume.

## Source of truth

- `options-alpha-agent-design.md` section 8, MVP strategy, exact payoff
  algebra, and pricing and scoring (lines 351 to 419).
- `options-alpha-agent-design.md` section 9, liquidity and data-quality gates
  (lines 420 to 446).
- `AGENTS.md`, the non-negotiable safety boundary and the engineering
  boundaries section: structure code enumerates real chains and exact bounded
  payoffs.
- `.claude/rules/01-safety.md`, on decimal/integer types for money, quantity,
  price, strike, and payoff.
- `.claude/rules/30-execution.md`, the new-entry fail-closed bullet: stale or
  crossed quotes, insufficient size, spread-width violation.
- `project-state/DECISIONS.md` D-014, on what a `StructurePlan` leg may
  contain and why, and D-023, on `plan_id` uniqueness per plan instance.
- `specs/units/011-order-schema-adapter.md`, whose merged `build_mleg_order` is
  this unit's consumer and whose declared leg vocabulary this unit must
  produce unchanged.
- `specs/units/012-order-state-machine.md`, whose `BrokerOrderLookup` Protocol
  and subprocess-determinism tests are the pattern this unit follows for
  `ChainLookup` and for `plan_id`.
- `orchestrator-system-prompt.md`, the `build_structure(candidate_id)` tool
  description, for what a caller above this unit eventually needs.
- `config/session.toml` and `config/risk.toml`, for the `strategy_allowlist`
  names and the `dte_min`/`dte_max` and `max_contracts_per_structure` values
  this unit's parameters mirror without reading the files directly.

## Scope

In:

- A frozen `ChainContract` record describing one real, quoted option contract:
  symbol, underlying symbol, option type, strike, expiry, bid, ask, displayed
  bid/ask size, contract multiplier, delta where available, quote time, and
  feed identity.
- A `ChainLookup` Protocol that returns already-typed `ChainContract` records
  for one underlying as of one timestamp, satisfied in tests by an in-memory
  fixture. No network access anywhere in this unit.
- Enumeration of admissible two-leg debit verticals from a chain: filtering by
  the DTE window, the absolute-delta bands for the long and short leg, and
  every liquidity and data-quality gate in design section 9.
- Exact payoff algebra per design section 8: net debit, width, maximum loss,
  maximum profit, and expiry breakeven, computed from signed leg prices in
  `Decimal`, generalized to the contract's own multiplier rather than a
  hardcoded 100.
- Rejection of every design-stated invalid spread: non-positive net debit,
  net debit at or above width, a mismatched underlying or expiry between legs,
  and a leg ratio other than one-to-one.
- Construction of `StructurePlan` for each admissible combination, with legs in
  exactly the vocabulary UNIT-011 already fixed, and a deterministic,
  documented ordering across multiple admissible combinations.
- A deterministic `plan_id` derived from the candidate id and the exact leg
  combination, satisfying the D-023 obligation that a plan id be unique per
  plan instance.

Out:

- Choosing which underlying to scan, ranking candidates against each other,
  or comparing forecast direction across symbols. That ranking already
  happened before `build_structure` is called for one candidate; the research
  lane and no unit yet named own it.
- Sizing the position and producing the risk approval token (UNIT-013).
  `quantity` arrives here only to check displayed size against it; this unit
  never derives a quantity.
- Mapping a `StructurePlan` to the Alpaca wire payload, canonical
  serialization, and the payload hash (UNIT-011, merged). This unit only
  produces a plan whose legs that mapping already accepts unmodified.
- The order state machine and client order id (UNIT-012, merged). `plan_id`
  here is a different identifier from `client_order_id` and is not submitted
  to a broker.
- Reconciliation and restart recovery of broker state (UNIT-015).
- The append-only ledger (UNIT-016) and the kill switch (UNIT-017).
- Any repricing model. No pre-expiry option repricer is validated yet per
  `project-state/STATUS.md`, so no constant-IV or adverse-IV stress mark, and
  no net Greek exposure, is produced. `stress_pnl` here holds only the two
  at-expiry boundary payoffs computable from the same exact algebra as
  `exact_max_loss`/`exact_max_profit`.
- Deciding whether indicative-feed options data may currently be used for a
  live trade at all. This unit only checks that an observed contract's feed
  equals the caller's stated expected feed; the policy of when indicative mode
  is permitted belongs to configuration and orchestration.
- The bounded entry price ladder from design section 11 step 4, owned by
  UNIT-018. `entry_limit_bound` here is the single conservative natural-debit
  bound; stepping it is not this unit's job.
- Parsing a raw Alpaca chain or contract wire payload. `ChainLookup` returns
  already-typed `ChainContract` records, the same way UNIT-012's
  `BrokerOrderLookup` returns an already-typed `BrokerOrder`. Whoever builds a
  live `ChainLookup` against Alpaca's actual chain schema owns that parsing,
  and no unit is assigned to it yet; this is a gap, named here the same way
  UNIT-011 and UNIT-012 name the price-ladder gap, not a silent absorption.
- Reducing this unit's ordered candidate list to the single result
  `build_structure(candidate_id)` in `orchestrator-system-prompt.md` returns.
  This unit's output is the deterministic order; a thin wrapper taking its
  head is unassigned and out of scope here.

## Contract

`alphaledger.structure.chains`, importing from `alphaledger.domain` and
nothing else in `alphaledger`. `alphaledger/structure/__init__.py` carries a
docstring and no re-exports, matching `alphaledger/execution/__init__.py`.

```python
class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"

StructureKind = Literal["bull_call_debit_vertical", "bear_put_debit_vertical"]

class StructureError(ValueError): ...

@dataclass(frozen=True, slots=True)
class ChainContract:
    symbol: str
    underlying_symbol: str
    option_type: OptionType
    strike: Decimal
    expiry: date
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    multiplier: int
    delta: Decimal | None
    quote_time: datetime
    feed: str

class ChainLookup(Protocol):
    def contracts_for(
        self, underlying_symbol: str, as_of: datetime
    ) -> Sequence[ChainContract]: ...

@dataclass(frozen=True, slots=True)
class StructureRules:
    dte_min: int
    dte_max: int
    long_abs_delta_min: Decimal
    long_abs_delta_max: Decimal
    short_abs_delta_min: Decimal
    short_abs_delta_max: Decimal
    max_quote_age: timedelta
    max_relative_spread: Decimal
    max_absolute_spread: Decimal
    expected_feed: str

@dataclass(frozen=True, slots=True)
class StructureEnumerationResult:
    candidates: tuple[StructurePlan, ...]
    rejection_reasons: tuple[str, ...]

def enumerate_candidates(
    kind: StructureKind,
    candidate_id: str,
    underlying_symbol: str,
    as_of: datetime,
    quantity: int,
    rules: StructureRules,
    chains: ChainLookup,
) -> StructureEnumerationResult: ...
```

`StructureRules.dte_min` refuses a value below 1 at construction. Design
section 8's "no same-day expiration" is a hard invariant of this unit, not a
configurable threshold, so it cannot be relaxed by a caller passing
`dte_min=0`. Every other bound in `StructureRules` is exactly the threshold
design section 9 asks for; none is hardcoded in this module, and none is read
from `config/`, since no committed file holds them yet and `config/**` is
outside this unit's declared paths. A future unit that wires a `structure.toml`
or extends `risk.toml` supplies these values; this unit only declares the
shape they must have.

`StructureEnumerationResult` mirrors the biconditional already established by
`Forecast.eligible`/`rejection_reasons`, but stricter: `candidates` non-empty
requires `rejection_reasons` empty, and `candidates` empty requires
`rejection_reasons` non-empty. A caller can therefore never confuse "no
admissible structure" with "an error occurred"; the former is this result with
empty `candidates` and populated reasons, the latter is `StructureError`
raised for a malformed input before enumeration runs at all.

`candidates` is a total, deterministic order, documented in the function's own
docstring: ascending by cost-drag ratio (net debit divided by width), ties
broken by the nearest expiry, remaining ties broken by the lowest long-leg
strike. This is stated as an order, not as a claim that the first element is
uniquely "best", because design section 8's own language, "liquidity, cost
drag, forecast alignment, and exact risk, not the nearest delta alone", never
resolves into one formula; forecast alignment already happened before this
function is called for one candidate at one fixed direction. A caller wanting
a single plan takes the head of this order; this unit's obligation ends at the
order being reproducible.

`plan_id` is `f"{candidate_id}/{long_leg.symbol}/{short_leg.symbol}"`: pure,
no clock, no randomness, distinct for every distinct leg combination under one
`candidate_id`, and identical across processes for the same inputs. This
satisfies the D-023 obligation the caller inherits, that `plan_id` be unique
per plan instance, so long as `candidate_id` itself is unique per decision
instance, which is a precondition on the caller carried over unchanged from
D-023.

### Leg vocabulary: not promoted to a typed record

D-014 notes UNIT-014 may promote a `StructurePlan` leg to a typed record as a
narrowing. This unit does not. `alphaledger.execution.orders`'s `_map_leg`
rejects any leg key outside `{"symbol", "ratio_qty", "side",
"position_intent"}` and requires all four present; this was read directly
before writing this intake. A typed record is not a `Mapping[str, object]`
with exactly that closed key set unless it is converted at the boundary, and
converting it would only reintroduce the same four-key mapping this unit can
emit directly. Every leg this unit produces is therefore exactly
`{"symbol": <OCC contract symbol>, "ratio_qty": 1, "side": "buy" | "sell",
"position_intent": "buy_to_open" | "sell_to_open"}`, which the merged
`build_mleg_order` accepts unmodified. This is a decision made from the
consumer's actual code, not from the design sketch, and is recorded here so a
reviewer does not reopen it without first reading the same lines.

### Multiplier: read, not assumed

Design section 8 writes the exact payoff algebra as `100D` and `100(W-D)`.
Design section 9 separately lists "missing contract metadata or inconsistent
multiplier" as a rejection gate, which only makes sense if the multiplier is
read per contract rather than assumed to always be 100, for example after a
corporate action. This unit resolves the conflict in favor of the gate: both
legs' `multiplier` field must be present and equal, the shared value is used
in place of the literal 100, and a mismatch excludes the combination under the
metadata gate instead of silently picking one leg's value. This is the same
kind of resolved conflict UNIT-001 recorded for `Decimal` over `float`, and it
is recorded here for the same reason.

## Assumptions

- `expiry` is `datetime.date`, not a UTC datetime. It names a contract's
  expiration date, not a point-in-time observation, and DTE is computed
  against `as_of.date()` in whole calendar days, not trading sessions.
- `delta` uses a small local exact-decimal helper, not the domain's `money()`.
  It rejects `float` the same way `money()` does, but is not quantized to the
  money exponent and its error message does not call a Greek "money". This
  mirrors the non-money `_exact_decimal` helper `alphaledger/config/__init__.py`
  already uses for a value that must be exact without being currency.
  `StructureKind` uses the two exact strings already frozen in
  `config/session.toml`'s `strategy_allowlist`, so a future config-reading
  caller can pass this unit's own output straight through a membership check
  without a translation table.
- Net debit is always long-leg ask minus short-leg bid, computed from the
  conservative, executable side of the quote, and used as both the value in
  the exact payoff algebra and `StructurePlan.entry_limit_bound`. The midpoint
  is deliberately not computed anywhere in this unit; design section 8 asks
  for it only as a sensitivity display, never as a bound, and nothing here
  displays anything.
- `exact_max_loss` and `exact_max_profit` are stored as positive magnitudes,
  matching the literal `100D` and `100(W-D)` forms in design section 8.
  `stress_pnl` stores the signed versions, `-exact_max_loss` and
  `+exact_max_profit`, under the keys `"max_loss_scenario"` and
  `"max_profit_scenario"`, so the two representations are never confused with
  each other.
- The search space is restricted at generation time to the option type and
  strike ordering a debit vertical of the requested `kind` requires; a
  same-underlying, same-expiry, wrong-order, or wrong-option-type pair is never
  constructed as a candidate to reject, so no path here can ever emit a naked
  short leg or a plan mixing two underlyings or two expiries.
- `quantity` is checked against `bid_size`/`ask_size` on both legs and against
  nothing else. It is not derived, floored, or capped by this unit; UNIT-013
  owns sizing, and a `quantity` this unit is handed is treated as already
  decided.

## Acceptance criteria

- AC-1: for a hand-written fixture with one admissible combination, the
  returned `StructurePlan`'s `exact_max_loss`, `exact_max_profit`, and
  `expiry_breakeven` match values computed by hand from design section 8's
  formulas, field by field, for both a call debit vertical and a put debit
  vertical.
- AC-2: a combination with non-positive net debit, a combination with net
  debit at or above width, a combination whose legs carry different expiries,
  and a combination whose legs carry different underlyings are each never
  present in `candidates` and never raise; each is observable only as an
  absent candidate against a fixture built to contain exactly that one flaw.
- AC-3: `StructureRules` refuses `dte_min` below 1 at construction, naming the
  field; a chain contract expiring on `as_of`'s own date is therefore
  impossible to select regardless of any other rule value.
- AC-4: each of the seven design section 9 gates independently excludes an
  otherwise-admissible combination when violated: zero or crossed bid/ask, a
  quote older than `rules.max_quote_age`, a missing or mismatched multiplier,
  a missing delta on a leg the delta-band rule needs, a bid/ask width beyond
  `rules.max_relative_spread` or `rules.max_absolute_spread`, a displayed size
  below `quantity` on either leg, and a feed unequal to `rules.expected_feed`.
  One fixture and one test per gate; each failure names the gate and the
  excluded contract symbol in `rejection_reasons`.
- AC-5: every leg in a produced `StructurePlan` has exactly the keys `symbol`,
  `ratio_qty`, `side`, `position_intent`, with `side`/`position_intent` pairs
  limited to `buy`/`buy_to_open` and `sell`/`sell_to_open`; a produced plan is
  accepted unmodified by `alphaledger.execution.orders.build_mleg_order`
  called with an approved quantity and limit price, without a `TypeError` or
  `OrderAdapterError`.
- AC-6: given a fixture with more than one admissible combination, the
  returned `candidates` order is identical across repeated calls in one
  process and across a separate process, and matches the rule stated in the
  function's docstring: ascending cost-drag ratio, then nearest expiry, then
  lowest long strike.
- AC-7: the same `candidate_id` with two different admissible leg
  combinations yields two different `plan_id` values, and the same
  `candidate_id` and combination yield the identical `plan_id` in a separate
  process.
- AC-8: two legs with a matching multiplier other than 100 produce a payoff
  scaled by that multiplier, not by 100; two legs with different multipliers
  are excluded under the metadata gate rather than one value being picked.
- AC-9: a `ChainContract` constructed with a `float` strike, bid, ask, or
  delta is refused at construction, naming the field; every money-shaped
  field on a produced `StructurePlan` is `Decimal`.
- AC-10: `stress_pnl` on every produced `StructurePlan` contains exactly the
  two keys `max_loss_scenario` and `max_profit_scenario`, equal to
  `-exact_max_loss` and `exact_max_profit`, and no other key.
- AC-11: a chain with no contracts for the underlying, and a chain whose only
  contracts are the wrong option type for the requested `kind`, each yield a
  `StructureEnumerationResult` with empty `candidates` and non-empty
  `rejection_reasons`, never a raised exception.
- AC-12: `kind` outside the two declared literal values is refused with
  `StructureError` before any contract is examined.

## Test list

- success: a two-leg call debit vertical fixture with quotes well inside every
  gate produces the expected `StructurePlan`, checked field by field against a
  hand-computed payoff (AC-1).
- success: the put debit vertical equivalent of the above, with the mirrored
  breakeven direction (AC-1).
- success: a produced plan passes unmodified into
  `alphaledger.execution.orders.build_mleg_order` (AC-5).
- success: a fixture with three admissible combinations returns them in the
  documented order, and a subprocess run against the identical fixture returns
  the identical order and identical `plan_id` values (AC-6, AC-7).
- success: a matching multiplier of 10 on both legs scales the payoff by 10,
  not by 100 (AC-8).
- failure: a `ChainContract` built with a `float` bid, ask, strike, or delta
  raises, naming the field (AC-9).
- failure: `enumerate_candidates` called with a `kind` outside the two
  declared values raises `StructureError` before touching the chain (AC-12).
- failure: `StructureRules` constructed with `dte_min=0` raises (AC-3).
- failure, one test per gate: a zero bid, a crossed bid over ask, a quote
  older than `max_quote_age`, a missing multiplier, a multiplier mismatch
  between legs, a missing delta on the leg the band rule needs, a bid/ask
  width beyond each of the relative and absolute thresholds, a displayed size
  below the requested `quantity`, and a feed unequal to `expected_feed`, each
  excluding an otherwise-admissible combination and naming the gate and symbol
  in `rejection_reasons` (AC-4).
- failure: a combination with non-positive net debit, a combination with net
  debit at or above width, a combination spanning two expiries, and a
  combination spanning two underlyings are each absent from `candidates` and
  never raise (AC-2).
- restart: the same fixture enumerated twice, once in the original process and
  once in a subprocess, yields `StructurePlan` objects equal field by field,
  not merely equal `plan_id` values (AC-1, AC-7).
- restart: `plan_id` derived from the same `candidate_id` and the same leg
  combination is identical across the process boundary, so a caller retrying
  after a crash before a risk approval was recorded reconstructs the same
  plan to re-request approval against (AC-7).
- no-trade: an underlying with no contracts returned by `ChainLookup` yields
  empty `candidates` and a populated reason, never an exception (AC-11).
- no-trade: a chain containing only puts when `kind` is
  `bull_call_debit_vertical` yields empty `candidates` and a populated reason
  naming the absent option type (AC-11).
- no-trade: a chain where every combination fails the delta bands yields
  empty `candidates`, distinct in its reason text from a gate failure (AC-4).

## Verification

```bash
uv run pytest tests/structure -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
