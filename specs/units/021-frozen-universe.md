---
id: UNIT-021
title: Generate the lagged frozen universe
lane: research
state: available
owner: -
branch: -
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001]
paths: src/alphaledger/data/universe.py
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
