---
id: UNIT-019
title: Derive the bounded entry rung price sequence from live quotes
lane: execution
state: merged
owner: pablo/codex
branch: feature/019-entry-rung-prices
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-014, UNIT-018]
paths: src/alphaledger/structure/pricing.py, tests/execution/test_pricing.py
claimed_at: 2026-08-31T18:59:58Z
reviewed_by: execution-safety-reviewer
review_verdict: clear
reviewed_at: 2026-08-31T19:31:04Z
review_log: [clear]
---

## Problem

`UNIT-018` steps a bounded entry price ladder and consumes an already-ordered
sequence of candidate limit prices. Nothing produces that sequence. `UNIT-018`
records the gap in its own Scope, Out, and merged deliberately without it,
testing against fixture price sequences the way `UNIT-013` and `UNIT-017` were
each merged before a real caller existed.

So the ladder is merged, the chain enumeration that carries the quotes is
merged, and the function between them is owned by no row in
`specs/000-INTAKE.md`. Design section 11 step 4 requires the ladder to start
near the executable midpoint and move toward the conservative natural price,
which is a statement about prices this project currently cannot compute.

This is not a missing convenience. Getting it wrong is the difference between a
backtest-flattering fill and a real one: a ladder that starts at the midpoint
and never reaches the natural price silently reports fills it would not have
received, and one that starts at the natural price pays the whole spread on
every entry.

## Source of truth

- `options-alpha-agent-design.md` section 11 step 4, for the midpoint to
  natural direction and the requirement never to cross the risk engine's price
  bound.
- `options-alpha-agent-design.md` sections 5 and 8, for the structure
  economics and the conservative cost stance.
- `specs/units/018-entry-price-ladder.md`, which names this gap and whose
  `step_ladder` consumes the output. Its refusals define the shape the sequence
  has to satisfy.
- `src/alphaledger/structure/chains.py`, merged by `UNIT-014`, for
  `ChainContract` and the quote fields available: `bid`, `ask`, `bid_size`,
  `ask_size`, `multiplier`, `quote_time`, and `feed`.

## Scope

In:

- A pure function producing the ordered sequence of candidate net debit prices
  for one `StructurePlan`, from the executable midpoint through to the
  conservative natural price, at a requested number of rungs.
- Deriving the two endpoints from the legs' own quotes, so a debit vertical's
  natural price pays the ask on what it buys and receives the bid on what it
  sells, and the midpoint uses each leg's own midpoint.
- Refusing, rather than repairing, a quote set that cannot support a sequence:
  a crossed or inverted market, a zero or absent size where the design requires
  a displayed size, a quote older than a supplied staleness bound, or a
  midpoint that already exceeds the plan's `entry_limit_bound`.

Out:

- Stepping the ladder, timing it, or producing a risk approval. That is
  `UNIT-018` and this unit must not duplicate its budget or its clock.
- Any I/O. The quotes arrive as already-materialized `ChainContract` values,
  exactly as `UNIT-013`'s `AccountSnapshot` and `UNIT-017`'s `EquityState` do.
- Choosing the rung count or the staleness bound. Both arrive as parameters,
  because `config/` commits neither today and inventing a second home for a
  threshold would cut across D-017 and `UNIT-005`.
- Exit pricing. `UNIT-018` is entry only and so is this.

## Contract

`alphaledger.structure.pricing.rung_prices(plan, quotes, rungs, max_quote_age,
as_of) -> tuple[Decimal, ...]`, pure and deterministic, no clock read.

`quotes` maps each of the plan's leg symbols to its `ChainContract`. Every leg
the plan names must be present; a missing leg raises rather than being priced
from the remainder.

The returned sequence is strictly increasing, has exactly `rungs` entries,
begins at the executable midpoint net debit, ends at the natural net debit, and
never exceeds `plan.entry_limit_bound`. Those are precisely the properties
`UNIT-018` refuses a sequence for lacking, so the two units agree by
construction rather than by convention.

Money is `Decimal` throughout with a declared rounding, per
`.claude/rules/01-safety.md`. Rounding is toward the conservative side, meaning
a debit rounds up, so a rounding step can never quietly produce a price better
than the market showed.

Errors: `UnpricableStructureError` when the quotes cannot support a sequence,
naming the leg and the condition.

## When you do not know

The natural price for a debit vertical is unambiguous: pay the ask on the long
leg, receive the bid on the short leg. Whether the sequence between midpoint
and natural is linear in price or weighted toward the midpoint is a genuine
choice this intake does not settle, and it is not marked
`[NEEDS CLARIFICATION]` because a linear sequence is the neutral default and no
evidence exists to prefer another. Whoever selects the ladder shape on
development data registers it as a trial, per
`.claude/rules/20-research-integrity.md`, and the rung count already lives with
the caller.

## Assumptions

`entry_limit_bound` is the risk engine's ceiling and is treated as a hard
refusal rather than a clamp. Clamping would silently produce a sequence whose
last rung is the bound rather than the natural price, which reads as a
completed ladder while being a truncated one.

A displayed size of zero is refused rather than treated as an unbounded market,
because a quote with no size behind it is not a price this project may act on.

## Acceptance criteria

- AC-1: the sequence begins at the executable midpoint and ends at the natural
  price. Falsified by a hand-computed two-leg fixture whose bid and ask are
  distinct, observing either endpoint.
- AC-2: the sequence is strictly increasing and has exactly `rungs` entries.
  Falsified by observing a repeat, a decrease, or a different length, each of
  which `UNIT-018` independently refuses.
- AC-3: a midpoint already above `entry_limit_bound` raises rather than
  returning a clamped or empty sequence. Falsified by observing any sequence at
  all from such a fixture.
- AC-4: a crossed market, where a leg's bid exceeds its ask, raises naming the
  leg. Falsified by observing a price derived from it.
- AC-5: a quote older than `max_quote_age` relative to `as_of` raises naming
  the leg and both instants. Falsified by observing a sequence built from a
  stale quote, which section 10 forbids acting on.
- AC-6: a leg the plan names but `quotes` omits raises. Falsified by observing
  a sequence priced from the remaining legs.
- AC-7: rounding is conservative, so every emitted price is greater than or
  equal to the unrounded value it derives from. Falsified by any price below
  its exact value, which would be a fill better than the market showed.
- AC-8: the output satisfies every refusal `UNIT-018` applies, checked by
  passing it to `step_ladder` rather than by restating the conditions.
  Falsified by a sequence this unit emits and that unit rejects.

## Test list

- success: a hand-computed two-leg debit vertical produces the exact midpoint
  and natural endpoints, with every intermediate rung hand-checked.
- success: a single rung sequence is the midpoint alone, since a ladder of one
  is a legal degenerate case rather than an error.
- failure: a crossed market raises, naming the leg.
- failure: a zero displayed size raises, naming the leg.
- failure: a stale quote raises, naming both instants.
- failure: a missing leg raises rather than pricing the remainder.
- failure: a midpoint above `entry_limit_bound` raises rather than clamping.
- restart: the same quotes produce a byte-identical sequence in a separate
  process, under two `PYTHONHASHSEED` values.
- no-trade: a structure that cannot be priced yields a refusal a caller records
  as a no-trade, never an empty sequence a caller could mistake for a ladder
  with no rungs left.
- integration: the emitted sequence is handed to `UNIT-018`'s `step_ladder`
  and accepted, which is AC-8 and is the only test here that crosses a unit
  boundary on purpose.

## Verification

```bash
uv run pytest tests/execution/test_pricing.py
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
