---
id: UNIT-021
title: Generate the lagged frozen universe
lane: research
state: in_review
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

