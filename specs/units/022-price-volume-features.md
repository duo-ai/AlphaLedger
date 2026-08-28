---
id: UNIT-022
title: Build residual price and volume features
lane: research
state: available
owner: -
branch: -
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-021]
paths: src/alphaledger/evidence/price_volume.py
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
