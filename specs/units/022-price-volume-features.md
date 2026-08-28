---
id: UNIT-022
title: Build residual price and volume features
lane: research
state: in_review
owner: mazwy/claude
branch: feature/022-price-volume-features
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-021]
paths: src/alphaledger/evidence/__init__.py, src/alphaledger/evidence/price_volume.py, tests/research/test_price_volume.py
claimed_at: 2026-08-28T19:56:15Z
---

## Problem

The price family is the baseline the news family has to beat. If it is not
built as a strict function of past observations, the comparison between
price-only, news-only, and combined models is meaningless, and a positive
result cannot be distinguished from a look-ahead.

## Source of truth

- `options-alpha-agent-design.md` section 5.1 for the feature list.
- `options-alpha-agent-design.md` section 4 for the timestamp contract.
- `.claude/rules/20-research-integrity.md` for leakage and winsorization rules.

## Scope

In:

- A rolling market and sector residual model over a lookback fixed before any
  live run.
- The features named in section 5.1: one-session and five-session residual
  return, opening gap residual, cumulative abnormal return from an event
  timestamp, residual-return z-score against trailing residual volatility,
  abnormal volume against a time-of-day baseline where intraday data exists and
  trailing daily volume otherwise, range over ATR, and proximity to a recent
  price extreme.
- Winsorization limits, missing-value behaviour, sector mapping, and lookback
  lengths as versioned configuration.
- A `feature_version` that changes whenever any of the above changes.

Out:

- News features (UNIT-023) and the model itself (UNIT-024).
- Any feature that requires an options quote. That is capability-gated and
  belongs to a later unit.

## Resolved conflicts

Two, both recorded before any code was written.

The declared `paths` did not name `src/alphaledger/evidence/__init__.py`, which
the module needs to be importable and which no other unit claims. It is added
here, following UNIT-011 and UNIT-020.

The contract line says `build(...) -> Mapping[str, float]`, but AC-3 requires a
missing marker and a quality flag, AC-4 requires the winsorization limits to be
recorded in the output, and AC-5 requires a `feature_version`. A mapping of
floats cannot carry any of those. `build` therefore returns a `FeatureBlock`
whose `.features` is exactly the `Mapping[str, float]` that populates
`EvidenceCard.price_volume_features`, with the flags, the limits, and the
version alongside it. The contract's own phrase, "the feature block", is read
as naming that object. The alternative, encoding flags as float sentinels,
would put a marker inside the number and is the more permissive reading.

A missing feature is absent from the mapping rather than present as NaN,
because `EvidenceCard` rejects NaN outright. Absence plus a named flag is the
missing marker AC-3 asks for.

## Contract

`alphaledger.evidence.price_volume.build(symbol, as_of, bars, config) ->
Mapping[str, float]` returning the feature block that populates
`EvidenceCard.price_volume_features`. Pure and deterministic: the same inputs
and config always produce the same output, with no clock read inside.

## Acceptance criteria

- AC-1: no feature reads a bar whose timestamp is later than `as_of`.
- AC-2: the same inputs and config produce identical output across processes.
- AC-3: an insufficient lookback yields an explicit missing marker and a
  quality flag, never a silently imputed zero.
- AC-4: winsorization limits come from config and are recorded in the output
  metadata, not hard-coded.
- AC-5: changing any config value changes `feature_version`.

## Test list

- success: a hand-computed fixture reproduces each feature to a stated
  tolerance, so the arithmetic is checked rather than merely exercised.
- success: two processes given the same fixture produce byte-identical output.
- failure: a bar stamped after `as_of` is present in the input and the builder
  rejects it rather than using it. This is the leaked fixture the research
  rules require.
- failure: a symbol with fewer bars than the lookback yields the missing marker
  and the quality flag, and is not silently zero-filled.
- failure: a config whose winsorization bounds are inverted is rejected at load
  rather than producing quietly clipped features.
- restart: rebuilding a past `as_of` from cached bars reproduces the same
  values, so a frozen run stays reproducible.
- no-trade: a symbol with no qualifying data yields an empty feature block with
  flags set, which the forecast layer must treat as ineligible rather than
  neutral.

## Verification

```bash
uv run pytest tests/research/test_price_volume.py -q
uv run ruff check . && uv run mypy src
```

## Handoff notes

Implemented as `src/alphaledger/evidence/price_volume.py`. All eight features
from design section 5.1 are present. `build` is pure, reads no clock, and takes
the panel the caller has already restricted to `as_of`.

### The model, and why it is this one

Rolling robust demeaning: the residual return for a session is the symbol's
return minus the median return of its sector peers. The median rather than the
mean, so one peer with a corporate action or a squeeze cannot drag the whole
cross-section, which is asserted by a test with a peer that moves twenty
percent. A sector with fewer peers than `min_sector_peers` falls back to the
whole panel and sets `sector_fallback_market`.

No betas are fitted. A regression would introduce configuration that has not
been selected on development data, and the design requires those choices to be
registered as trials and frozen first. The median demeaning is already a strict
function of past observations, which is what this unit has to guarantee.

### Boundaries the tests pin

`bars` is an `as_of` restricted panel, the same shape as UNIT-021's source. A
bar first seen after `as_of` raises rather than being dropped, including the
case where that would leave nothing: an unfiltered panel at an early `as_of`
stops instead of reporting an empty block, because "no data" and "data you must
not use" are different answers and a caller who confused them would read a leak
as a quiet no-trade. Two bars for one symbol and session that disagree raise,
the same rule the universe builder needed.

The volume baseline and the ATR window both exclude the session being measured,
each pinned by a test that fails if the window is widened by one.

### Verified

- `uv run pytest tests/research/test_price_volume.py -q`: 29 passed.
- `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy src`,
  `pytest`: all pass, 167 tests.
- Every feature is checked against a hand-computed value from a fixture built
  so the arithmetic can be redone on paper: the peers are flat, so the sector
  median is zero and each residual equals the raw return.
- Determinism is asserted across two processes under different
  `PYTHONHASHSEED` values, comparing the full output byte for byte.
- Twenty-two defects were injected one at a time and every one was caught by a
  named test. Three survived the first pass and each exposed a real fixture
  weakness rather than a false alarm: identical peers made a mean
  indistinguishable from a median, a twenty session volume baseline of equal
  volumes made the off-by-one window invisible, and an event session with no
  move made the inclusive and exclusive windows identical. All three now have
  fixtures that separate them.

### Review round one, backtest-auditor

Seven findings, all addressed. The first two are the ones that mattered.

- Same-bar contamination in the event feature. The cumulative abnormal return
  window compared `event_time` against each session's own close stamp. A news
  item is stamped mid-session, earlier than that day's close, so the event
  session was included and its close to close return, which spans the hours
  before the event, was counted as reaction. That is the exact leak this family
  exists to be clean of. The window now includes a session only when the whole
  return period, previous close to close, falls after the event. A test with an
  intraday event pins it, and another spans two sessions so a builder returning
  only the last residual cannot pass.
- Silent drop and positional misattribution. A zero prior close was skipped
  with no flag, and residual values were then paired back to sessions by
  position, so every residual before such a gap was attributed to the wrong
  session. `Bar` now refuses a non-positive price outright, which removes the
  skip, and residuals carry their session rather than being realigned by index.
- A close outside its own high and low was accepted, which made
  `proximity_to_extreme` unbounded in the one feature deliberately exempt from
  winsorization. `Bar` now refuses it, so the exemption rests on an enforced
  invariant rather than an assumed one.
- `sector_fallback_market` was set even when the panel held no peers at all, so
  a raw return looked like one demeaned against a broad median. A separate
  `no_peer_data` flag now says which happened.
- `FeatureConfig` allowed a `lookback_sessions` shorter than the volatility
  window, which starved the z-score and then reported insufficient history,
  blaming the data for a configuration mistake. Rejected at load.
- Three test-quality defects, all real. One assertion was a tautology, one was
  a no-op on an unused local, and the determinism script never passed an
  `event_time`, so the byte-identical claim covered a subset of the output and
  specifically excluded the code path both findings above lived in.
- The sample standard deviation convention behind the z-score was disclosed
  only in a test comment. It is now in the module docstring, where a consumer
  of the feature block will see it.

Twenty-seven defects were injected one at a time after these fixes and every
one is caught by a named test. Two were additionally checked by hand after the
harness returned an inconsistent verdict on one of them; both are caught.

### Review round two, backtest-auditor

No new defects. All seven round one fixes were verified by independent
reconstruction rather than by rerunning this branch's suite. The event window
boundary was probed at five positions, including an event exactly on a session
close, an event outside the panel at both ends, and a panel with a holiday gap;
the reviewer's own first expectation on the gap case was wrong and the code was
right.

One residual finding, now fixed. `no_peer_data` was a bare flag, so a block
where one session of twenty four was left undemeaned looked identical to a
block where nothing was ever demeaned. The z-score would then mix one raw
return into its window with nothing saying how much of the block that was. The
flag now carries the count, and a test distinguishes one missing session from a
panel with no peers at all.

### Open question for the adapter, deliberately not answered here

`Bar` now refuses a non-positive price and an open or close outside its own
high and low. Both are tautologically true of a well formed OHLC bar, and both
fail closed. The unverified case is cross-vendor reconciliation: a busted or
corrected trade, or a mismatch between an adjusted close and unadjusted highs
and lows around a corporate action, could in principle produce an inconsistent
print from a real feed, which would now halt rather than flag and continue.

Whether Alpaca's raw or adjusted bar history ever emits a close outside its own
range is a question for `alpaca-docs-researcher`, and it should be answered
before UNIT-020's adapter feeds this module rather than discovered when it
does. Halting is the reading `.claude/rules/01-safety.md` asks for, so the
answer should confirm or overturn a stated decision, not settle an accident.

### Not verified

- No adapter produces `Bar` records from Alpaca. Every bar here is a fixture.
- Intraday data is absent, so abnormal volume uses the trailing daily baseline
  that design section 5.1 names as the fallback, and every block says so with
  `abnormal_volume_daily_baseline`. The time-of-day baseline is unimplemented.
- The lookbacks, the winsorization limits, and the sector map are declared
  defaults, not values selected on development data and registered as trials.
  Section 5.1 requires that selection before any live run, and it has not
  happened. `feature_version` changes when they change, which is what makes the
  selection auditable later.
- Nothing yet compares this family against news or combined baselines. That is
  the comparison this unit exists to be the control in, and it belongs to
  UNIT-023 and UNIT-024.

