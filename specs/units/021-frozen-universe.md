---
id: UNIT-021
title: Generate the lagged frozen universe
lane: research
state: merged
owner: mazwy/claude
branch: feature/021-frozen-universe
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001]
paths: src/alphaledger/data/universe.py, tests/research/test_universe.py
claimed_at: 2026-08-28T19:34:04Z
---

## Problem

Every cross-sectional claim depends on the set of symbols being decided before
the session it applies to. If membership is computed from data inside the
session, the scan silently selects the names that already moved, and the whole
research result becomes a description of the past rather than a forecast.

## Source of truth

- `options-alpha-agent-design.md` section 4, frozen universe rule.
- `.claude/rules/20-research-integrity.md`, universe and survivorship rules.
- `hackathon-build-plan.md` section 5, morning block.

## Scope

In:

- A generator that, given a prior close, returns the next session's symbol set.
- The five membership conditions from design section 4: active, tradable and
  options enabled; at least ten dollars at the prior close; top cohort by
  trailing twenty-session median dollar volume; at least one 7 to 21 DTE
  expiration quoted two-sided near the money; and free of unresolved symbol
  changes or corporate actions.
- A hard cap of thirty symbols, and a recorded hash of the resulting set.
- The checked-in static fallback list, used only when point-in-time
  optionability history cannot be assembled, and flagged when used.

Out:

- Feature construction (UNIT-022) and forecasting (UNIT-024).
- Any path that lets a caller inject a symbol into a live candidate set. A
  read-only demo lookup belongs to the presentation layer, not here.

## Contract

`alphaledger.data.universe.build(as_of, source) -> FrozenUniverse` where
`FrozenUniverse` carries the symbol tuple, the `as_of` used, the liquidity
floors applied, the fallback flag, and a stable content hash. The function is
pure with respect to its `source`; it performs no network calls itself.

## Acceptance criteria

- AC-1: membership at `as_of` uses only observations whose `first_seen_time` is
  at or before `as_of`.
- AC-2: a symbol that becomes liquid or optionable only after `as_of` is absent
  from the set built at `as_of`.
- AC-3: a symbol delisted after `as_of` is still present in the set built at
  `as_of`. Survivorship is not applied retroactively.
- AC-4: the set never exceeds thirty symbols, and the applied floors are
  recorded alongside it.
- AC-5: building twice from the same inputs yields an identical hash.
- AC-6: using the static fallback sets the flag and records the list hash.

## Test list

- success: a fixture of symbols and prior closes produces the expected set, and
  rebuilding it yields the same hash.
- success: the cap holds when more than thirty symbols qualify, and the ones
  kept are the highest by median dollar volume.
- failure: a symbol whose only qualifying liquidity appears after `as_of` is
  excluded. This is the deliberately leaked fixture the research rules require.
- failure: a symbol with an unresolved corporate action is excluded and the
  reason is recorded.
- failure: a source that returns an observation stamped after `as_of` is
  rejected rather than filtered silently.
- restart: rebuilding from the recorded hash and inputs reproduces the set
  exactly, so a frozen run can be verified after the fact.
- no-trade: a date on which no symbol clears the floors returns an empty
  universe with the floors recorded, not an error and not a relaxed retry.

## Verification

```bash
uv run pytest tests/research/test_universe.py -q
uv run ruff check . && uv run mypy src
```

## Handoff notes

Implemented as `src/alphaledger/data/universe.py`. `build(as_of, source)` is
pure with respect to its source and performs no I/O. The source is a protocol,
so the recorder from UNIT-020 can back it later without changing this module.

### Interpretation recorded, because the design leaves it open

Design section 4 allows a checked-in static list when point-in-time
optionability history cannot be assembled, and requires the limitation to be
disclosed, but does not say what the list replaces. This module reads it
narrowly: membership in `STATIC_FALLBACK_SYMBOLS` stands in for the
optionability evidence alone, `options_enabled` and the near-money expiration
check. Price, dollar volume, tradability, and corporate-action screens still
come from point-in-time data, because those are reconstructable whether or not
optionability is. A wider reading, where the list replaces the whole screen,
would discard point-in-time evidence that is actually available.

The fallback flag and the list hash are recorded and both feed the universe
hash, so a fallback run and a reconstructed run can never produce the same
address. That is asserted directly.

### Ordering and the cap

Symbols are returned in rank order, dollar volume descending and symbol
ascending, not alphabetically, because the ranking is what a later stage
consumes. The cap is thirty, enforced in `UniverseFloors`, which refuses a
larger value rather than trusting a caller.

### Verified

- `uv run pytest tests/research/test_universe.py -q`: 23 passed.
- `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy src`,
  `pytest`: all pass, 131 tests.
- The restart test rebuilds in two subprocesses under different
  `PYTHONHASHSEED` values and asserts the same hash and the same set, which is
  what makes a frozen run verifiable by someone else later.
- Twenty defects were injected one at a time. Eighteen were caught by a named
  test. The two survivors are equivalent mutants: collecting symbols in sorted
  order and breaking a volume tie by symbol are each redundant while the other
  stands, so removing one alone changes no output. Removing both does, and
  `test_the_set_order_does_not_depend_on_the_order_the_source_returned_rows`
  catches that. Both mechanisms are kept because relying on the coupling would
  be a trap for the next change.

### Review round one, backtest-auditor

One blocking finding, two medium, and the fallback interpretation confirmed as
defensible and correctly implemented.

- Blocking, and correct. `_latest_per_symbol` resolved a tied `first_seen_time`
  with `>=`, so two observations of one symbol stamped identically were decided
  by whichever the source returned last. The reviewer showed this flipping
  membership between two arrival orders of the same two facts. It is not an
  edge case: the UNIT-020 recorder derives `first_seen_time` as `source_time`
  plus a fixed lag for any feed that cannot prove delivery, so every
  observation sharing a source time collides exactly. Changing `>=` to `>`
  would not have fixed it, only moved the arbitrariness to the first row.
  Tied observations that disagree now raise `AmbiguousObservationError` naming
  the symbol and the timestamp. Tied observations that agree are one fact and
  are accepted.
- Medium. `SymbolObservation` carried no feed, so a universe built from
  consolidated volumes and one built from a single venue were
  indistinguishable by hash, against design section 4's requirement to store
  the feed on every record. `feed` is now required, and the sorted feeds behind
  the kept symbols are recorded and hashed. Adding this after the first frozen
  run would have invalidated every recorded hash.
- Medium. The exclusion record kept only the first failed condition, and the
  corporate-action screen ran last, so a symbol with a pending split and a
  stale close was recorded as `below_price_floor` alone. That reads as routine
  exactly when the number is the untrustworthy part, because an unadjusted
  close is what a pending split leaves behind. `Exclusion` now records every
  failed condition, identity first, then optionability, then the floors.
- Low, accepted as stated. The universe hash addresses the decided set, not the
  evidence behind it, so two different bodies of evidence that rank to the same
  members under the same floors share an address. That is what AC-5 asks for.
  The docstring said "the inputs that decide membership", which claimed more,
  and now says what it does.
- Confirmed rather than changed: the exact-equality boundary at `as_of` was
  already correct and is now pinned by a test, and the reviewer independently
  checked the two equivalent mutants and agreed with that judgement.

Twenty-four defects were injected one at a time after these fixes. All but the
two known equivalent mutants were caught by a named test.

### Review round two, backtest-auditor

No new blocking findings. The three round one fixes were confirmed correct and
their tests confirmed non-vacuous. One gap was found and closed, and two of my
choices were challenged and upheld.

- Low to medium, now fixed. `feeds` was collected from the surviving symbols
  only, so a build mixing two feed definitions was invisible to the hash
  whenever the odd feed sat among the screened out or capped away names, which
  is most of them. Design section 4 wants a change of feed to be impossible to
  miss, not impossible to miss only in the top cohort. `feeds` now covers every
  observation considered.
- Upheld, halting rather than excluding. An ambiguous tie raises and no
  `FrozenUniverse` is produced for that instant, rather than the one symbol
  being excluded with a reason. `.claude/rules/01-safety.md` requires a
  fail-closed halt on exactly this kind of uncertainty, and `LeakedObservation`
  already halts a whole build for one bad row. Splitting the two would be an
  unprincipled asymmetry between two symptoms of the same broken source. The
  reviewer states the opposite choice would have been the defect.
- Upheld, full dataclass equality for the ambiguity check. There is no field on
  `SymbolObservation` that could be excluded from the comparison without
  reopening the same order dependence one field later, because every field
  either decides membership or reaches the hash through `feeds`.

### Obligation this unit hands to its caller

Neither `LeakedObservationError` nor `AmbiguousObservationError` is caught
anywhere in this module, so both propagate out of `build` and no universe is
returned for that instant. Whatever schedules a build must treat them as
fail-closed halts. Retrying with a relaxed source, or falling back to the last
good universe, would reintroduce exactly what they exist to stop.

### Not verified

- No adapter connects a real feed to `UniverseSource`. Every screening fact in
  these tests is a fixture, so the conditions are proven to be applied, not
  proven against Alpaca asset, bar, or chain data.
- The floors themselves are placeholders with declared defaults, ten dollars
  and ten million in median dollar volume. Design section 4 requires them to be
  selected on development data, registered as a trial, and frozen before the
  first autonomous session. That selection has not happened.
- `STATIC_FALLBACK_SYMBOLS` is a hand-written list of thirty liquid optionable
  names. It has not been checked against a point-in-time source, which is the
  whole reason it is a disclosed fallback rather than a screen.

