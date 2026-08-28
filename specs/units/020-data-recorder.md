---
id: UNIT-020
title: Record point-in-time observations with the timestamp contract
lane: research
state: in_review
owner: mazwy/claude
branch: feature/020-data-recorder
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001]
paths: src/alphaledger/data/__init__.py, src/alphaledger/data/recorder.py, src/alphaledger/data/storage.py, tests/research/__init__.py, tests/research/test_recorder.py
claimed_at: 2026-08-28T19:04:14Z
---

## Problem

Every research claim depends on being able to say what was knowable at the
moment of a prediction. If observations are stored without their arrival and
revision timestamps, no later audit can distinguish a genuine forward forecast
from a look-ahead, and the whole research lane becomes unfalsifiable.

## Source of truth

- `options-alpha-agent-design.md` section 4, timestamp contract.
- `.claude/rules/20-research-integrity.md`.
- `hackathon-build-plan.md` section 5, morning block.

## Scope

In:

- A recorder that persists raw responses with `event_time`, `first_seen_time`,
  `source_time`, `received_time`, `feed`, and `as_of`.
- The documented conservative availability lag where a delivery time cannot be
  proven.
- Rejection of any observation whose timestamps imply knowledge of the future.
- Feed identity stored on every record.

Out:

- Feature construction (UNIT-022) and labelling (UNIT-023).
- Universe membership (UNIT-021).

## Resolved gaps

The declared `paths` originally named three files but not the two package
markers those files need to be importable: `src/alphaledger/data/__init__.py`
and `tests/research/__init__.py`. Neither package exists yet and neither is
claimed by another unit, so both were added to `paths` here before any code was
written. UNIT-011 declares its own `execution/__init__.py`, so this follows the
established convention rather than introducing one.

## Inherited obligation

Per D-014, `ObservationTimestamps` enforces only `first_seen_time >=
source_time`. Every other ordering among the six timestamps is this unit's
responsibility, because only the adapter knows the feed semantics. In
particular `event_time` may legitimately follow `first_seen_time` for a
scheduled event, so the check here is feed-aware rather than a blanket sort.

## Contract

`alphaledger.data.recorder.record(observation) -> ObservationId`, append-only.
Reads are `as_of` queries that return only what was first seen at or before the
requested instant. There is no interface that returns a record by wall-clock
time alone, because that is the shape of a leak.

## Acceptance criteria

- AC-1: every persisted record carries all six timestamp fields and a feed id.
- AC-2: an `as_of` read never returns a record whose `first_seen_time` is later
  than the requested instant.
- AC-3: an observation with `first_seen_time` earlier than `source_time` is
  rejected as impossible.
- AC-4: a revision of an article is stored as a separate observation, not an
  update, and both remain retrievable.
- AC-5: where delivery time is unprovable, the recorded `first_seen_time` is
  the published time plus the documented lag, and the record is flagged.

## Test list

- success: a recorded observation is retrievable by an `as_of` at or after its
  first-seen time.
- success: a revision and its original are both retained and distinguishable.
- failure: an observation timestamped in the future relative to `as_of` is
  rejected, naming the offending field.
- failure: a record missing `feed` is rejected rather than defaulted.
- failure: a deliberately leaked fixture, where `first_seen_time` precedes
  `source_time`, is rejected. This is the fixture required by
  `.claude/rules/20-research-integrity.md`.
- restart: the recorder reopens an existing store append-only and does not
  rewrite or reorder prior records.
- no-trade: an `as_of` read with no qualifying observations returns an empty
  result, not an error and not the most recent record.

## Verification

```bash
uv run pytest tests/research/test_recorder.py -q
uv run ruff check . && uv run mypy src
```

## Handoff notes

Implemented as `src/alphaledger/data/storage.py`, a JSON Lines file opened only
in append mode, plus `src/alphaledger/data/recorder.py`, which owns validation,
availability derivation, and the `as_of` read.

### Orderings enforced here, per the D-014 obligation

Universal, every feed:

1. `first_seen_time >= source_time`. Checked here as well as in the domain type
   so the rejection names the field and the feed.
2. `received_time >= source_time`. A value is either a live arrival or a
   backfill fetch, and both follow emission.
3. `first_seen_time <= as_of`. `as_of` is the knowledge cutoff the record is
   filed under, so a later first-seen would place a future observation inside a
   point-in-time snapshot.

Feed aware, from `FeedPolicy`:

4. `event_time <= first_seen_time` unless the feed declares
   `event_time_may_follow_first_seen`. This is the D-014 exception: a calendar
   feed sets it, a bar feed never does.
5. `first_seen_time >= received_time` for a feed that proves delivery. Not
   enforced otherwise, because a backfilled article's fetch time says nothing
   about when a subscriber could have read it.

A feed with no registered policy is rejected. There is no default policy,
because a default would be an unchecked assumption about timestamp semantics.

### Two deliberate choices worth a reviewer's attention

A feed that cannot prove delivery does not accept a caller supplied
`first_seen_time` at all. It is derived as `source_time` plus the policy lag and
flagged `availability_lag_applied`. Accepting one and quietly taking the more
conservative of the two would have hidden an optimistic caller.

Rule 2 was chosen without a real feed connected. If a live feed is found whose
publisher clock legitimately runs ahead of ours, this is the rule to revisit,
and the revisit belongs in `project-state/DECISIONS.md` rather than in a local
relaxation.

### Verified

- `uv run pytest tests/research/test_recorder.py -q`: 29 passed.
- `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy src`, `uv run pytest`: all pass, 93 tests.
- Twelve defects were injected one at a time and every one was caught by a
  named test. The first pass found a real weakness: the float payload test
  asserted only the field name, so it passed against a deleted money check. It
  now asserts the reason as well.
- The restart tests spawn real `sys.executable` subprocesses and assert that
  the file's earlier bytes are a strict prefix after each restart.

### Not verified

- No real feed is connected. Every timestamp in these tests is a fixture, so
  the ordering rules are proven self consistent, not proven against Alpaca.
- Concurrent writers are not tested. Two processes appending to one store is
  plausible under the current design but unproven, and nothing yet needs it.
- Store size, rotation, and retention are untouched.

### Hazard for the next session

Mutation testing rewrote a source file to the same byte length within the same
second, so CPython reused the cached bytecode and four unrelated tests failed
against a mutation that had already been reverted. Set
`PYTHONDONTWRITEBYTECODE=1` for any harness that edits sources in place.
