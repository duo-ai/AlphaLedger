# Research lane brief

This file delegates the research lane. It is written for the coding agent that
will work it, and it assumes you have read `ONBOARDING.md` first. That file
tells you how to work here. This one tells you what the work is, why it is
shaped the way it is, and where it goes wrong.

It is long because the alternative is you discovering these things one stop at
a time. Read it once, fully, before you claim anything.

## What is delegated to you

Three units, in this order:

| Unit | Title | State |
|---|---|---|
| UNIT-020 | Record point-in-time observations with the timestamp contract | merged |
| UNIT-021 | Generate the lagged frozen universe | merged |
| UNIT-022 | Build residual price and volume features | merged |
| UNIT-024 | Split chronologically and register every trial | merged |
| UNIT-003 | Enumerate the news category on the label | claimable now |
| UNIT-023 | Encode point-in-time news into features | blocked by UNIT-003 |

The first four are done. The evidence and validation scaffolding they built is
what everything below now rests on, so read their handoff notes before starting
UNIT-003: they record decisions you would otherwise have to rediscover.

UNIT-003 is small and sits in the shared lane rather than the research one, but
UNIT-023 depends on it, so it is the thing standing between you and the news
family. Take it first.

You own these paths and nothing else:

```
src/alphaledger/data/**
src/alphaledger/evidence/**
src/alphaledger/forecast/**
research/**
tests/research/**
```

Each unit's frontmatter narrows that further to specific files. Stay inside
your unit's declared `paths`, not merely inside the lane. Two agents editing
one file is the failure the whole coordination layer exists to prevent, and
`scripts/coord.py` will refuse a claim that overlaps work already in progress.

## What is not delegated to you

The execution lane. Orders, risk, reconciliation, the broker adapter, the
kill switch. Those are `src/alphaledger/{broker,execution,risk,structure,ledger}/**`
and they belong to the other lane. If a unit of yours appears to need a file
there, that is a decomposition error. Say so and stop; do not reach across.

Also not yours: the frozen domain contracts in `src/alphaledger/domain/**`.
They are merged and stable. You import from them. If one genuinely needs to
change, that is a conversation, not an edit.

## The state you are inheriting

Two units are merged and you can rely on them.

**UNIT-001, the domain contracts.** `src/alphaledger/domain/contracts.py`
holds the five records from design section 14 plus `ObservationTimestamps`.
Things you will care about:

- `money(value, field)` rejects `float` outright. It accepts `Decimal`, `str`,
  and `int`, requires finiteness, and quantizes to four places with
  `ROUND_HALF_EVEN`. Do not re-round after it.
- Every timestamp field is timezone-aware UTC. A naive datetime is rejected at
  construction, naming the field.
- Feature mappings reject `NaN` and `Infinity`. A zero denominator producing
  `NaN` is a routine event in feature code and it will raise here rather than
  silently poison a downstream calculation. Handle it in your code and set a
  quality flag; do not work around the check.
- A bare string is rejected where a tuple of strings is expected. A string is
  iterable, so an unguarded coercion would shred one reason into a tuple of
  characters. Pass `("reason",)`, not `"reason"`.

**UNIT-010, the paper endpoint assertion.** Yours only in that it proves the
system cannot reach a live host. You will not touch it.

### What the merged research units already give you

Read their handoff notes; this is only the shape.

- `data/recorder.py` and `storage.py`: six timestamps and a feed on every
  record, an `as_of` read with no wall-clock alternative, orderings judged feed
  by feed under the obligation D-014 hands the adapter, and `record` idempotent
  across a restart. D-015 records why a corrupted store refuses writes as well
  as reads rather than truncating to the last readable line.
- `data/universe.py`: membership decided at the prior close from evidence
  knowable then, capped at thirty, hashed so a frozen run is verifiable in
  another process. Tied timestamps and unregistered feeds are refused rather
  than resolved.
- `evidence/price_volume.py`: the eight features from design section 5.1. A
  missing feature is absent and named in a flag, never an imputed zero.
- `forecast/`: an expanding walk-forward purged by at least the horizon, and an
  append-only trial registry that refuses a result for an unregistered trial and
  refuses a second result over the first.
- `NewsLabel` was amended by UNIT-002 under D-016 so the record holds what the
  labeler actually emits, including `entity_match` and `unknown`. Read D-016
  before touching anything news-shaped: it draws the line between what the
  frozen record enforces and what the adapter enforces.

## Why this lane is different

The execution lane fails loudly. A wrong order is visible in an account.

Your lane fails silently. A leaked timestamp does not raise, it produces a
result that looks good. The whole claim of this project is that its signals
were validated chronologically on information actually available at the time.
A single look-ahead does not make the number slightly optimistic; it makes the
number meaningless, and worse, unfalsifiable, because nothing downstream can
tell the difference.

So the discipline below is not process for its own sake. It is the only thing
separating a forecast from a description of the past.

## The point-in-time discipline

Read `.claude/rules/20-research-integrity.md`. It binds your paths. The parts
that will actually bite:

**Every observation carries six timestamps**: `event_time`, `first_seen_time`,
`source_time`, `received_time`, `feed`, and `as_of`. Features are reconstructed
as of `first_seen_time`. A revision published later is a different observation,
not an update to an existing one.

**The domain type enforces exactly one ordering**, `first_seen_time >=
source_time`, because you cannot observe a record before its source emitted it.
Every other ordering is deliberately left to you, and this is recorded as
D-014 in `project-state/DECISIONS.md`. The reason matters:

> `event_time` may legitimately fall after `first_seen_time`. A scheduled
> earnings date is known weeks ahead. A domain type that rejected that would
> corrupt exactly the point-in-time evidence it exists to protect.

So your recorder is the thing that knows feed semantics and must judge the
rest. Do not add a blanket chronological sort. Judge per feed, and write down
which orderings you enforce and why.

**Where delivery time cannot be proven**, treat the published timestamp as a
lower bound, add the documented conservative latency buffer, prefer immutable
fields, and flag the record. If a point-in-time version cannot be reconstructed
without a plausible look-ahead path, exclude the field or the article. Excluding
data is an acceptable outcome. Guessing is not.

**Universe membership is lagged and reproducible.** Never filter historical
rows by current tradability, current optionability, current constituents, or
future liquidity. A symbol that became liquid after your `as_of` is absent. A
symbol delisted after your `as_of` is still present. Survivorship is not
applied retroactively.

**Chronological splits, purged by at least the forecast horizon.** Fitting,
calibration and threshold selection, and the locked test are separate windows
in time order. Overlapping labels are purged.

**Register every trial before you look at its result.** A failed or abandoned
variant stays in the registry. This is what makes the final number honest.

## What a good test looks like here

Your unit intake already contains a `## Test list` written before the unit
became claimable. That list is the specification. Do not invent tests instead
of it, and do not skip its awkward entries.

Four paths, every unit: **success, failure, restart, and no-trade**. The last
one is not decoration. An empty result is a first-class outcome in this system
and it must be tested with the same seriousness as a populated one.

Three failure modes we have already hit here, so you do not have to:

**Do not assert on a mock incapable of the failure you are naming.** A review
on the execution lane found a test called "redirect is rejected" whose fake
transport could not follow a redirect at all. It would have passed even while
the real failure occurred. If your test double cannot exhibit the bug, your
test proves nothing about the bug.

**A restart test needs a real process boundary.** An in-process re-invocation
demonstrates the language's data model, not restart behaviour. Spawn a
subprocess with `sys.executable` and assert on its output. That is the only
version that catches a module-level cache added later.

**A test that would pass against the defect is worse than no test**, because it
buys false confidence. Before you write an assertion, ask what would have to
break for it to fail. If the answer is "nothing in the code I am testing", the
assertion is wrong.

And one specific to your lane, required by the rules and not optional:

**Every research unit includes a deliberately leaked fixture that the pipeline
must reject.** An observation stamped after `as_of`. A bar that arrived late. A
universe row whose liquidity only appears later. The test asserts the rejection,
naming the offending field. If your pipeline silently filters it instead of
rejecting it, that is a defect, because silent filtering is how a leak becomes
invisible in production.

## The three units

### UNIT-020, the point-in-time recorder

The foundation. Everything downstream inherits whatever discipline you build
here, so this is the unit worth being slowest on.

It records raw observations with all six timestamps and the feed identity, and
its read interface is an `as_of` query that returns only what was first seen at
or before the requested instant. There is deliberately no interface that
returns a record by wall clock time alone, because that is the shape of a leak.

Note the obligation D-014 hands you: the domain type checks only `first_seen >=
source`. The rest of the ordering judgment is yours, feed by feed.

### UNIT-021, the frozen universe

At each prior close, produce the next session's symbol set from the five
conditions in design section 4. Cap at thirty. Record a hash of the resulting
set so a frozen run can be verified afterwards.

The whole point is that membership is decided before the session it applies to.
If membership is computed from data inside the session, the scan selects the
names that already moved, and every result after it describes the past.

There is a checked-in static fallback list for when point-in-time optionability
history cannot be assembled. Using it is allowed. Using it silently is not:
set the flag and record the list hash.

### UNIT-022, residual price and volume features

The baseline the news family has to beat. Its value is entirely in being a
strict function of past observations, because it is the control in the
comparison that decides whether news adds anything.

Winsorization limits, missing-value behaviour, sector mapping, and lookback
lengths are configuration, not judgment. They are versioned and frozen, and
changing any of them changes `feature_version`.

An insufficient lookback yields an explicit missing marker and a quality flag.
It never yields a silently imputed zero. A zero is a value; a missing marker is
the truth.

## The loop

```bash
# take work
python3 scripts/coord.py list --lane research
python3 scripts/coord.py claim UNIT-020 --owner <your-handle>/claude
# run the exact commands it prints: a one-line claim commit, then a worktree

# in the worktree, invoke the tdd-workflow skill and follow it
#   tests from the list, watch them fail, implement, refactor

# before handing off, invoke verification-loop, or run the gate directly
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest

python3 scripts/coord.py state UNIT-020 in_review
# then request backtest-auditor, the reviewer named in your frontmatter
```

Merge into `develop` with `--no-ff` only after the reviewer has reported and
you have addressed the findings. Then set the unit to `merged`, which is what
unblocks whatever depends on it.

Expect the review to find things. On this repository, two rounds on one unit
took it from nine tests to sixty-four, and the second round caught a bug that
the first round's own fix had introduced. That is the process working, not
failing.

## Hard constraints

Enforced by a `PreToolUse` hook, so you will hit them rather than remember them:

- Write only inside your unit's declared `paths`.
- Never commit to `main`. `develop` takes exactly one kind of direct commit,
  the registry claim.
- Branches are `feature/*`, `bugfix/*`, `release/*`, `hotfix/*`, `support/*`.
- Conventional commit subjects, for example `feat(data): record point-in-time bars`.
- No AI attribution trailers, no "Generated with" lines, no robot emoji.
- No em dashes or en dashes, in commits or in prose.
- No reads or writes of `.env`, credentials, or private keys.
- Paper trading only. Never introduce the live host, a `--live` path, or a way
  to disable paper mode.
- The Alpaca MCP server is market-data-only. Orders never flow through a raw
  tool.

And one the hook cannot enforce, which matters more than any of them:

**Never weaken a test, loosen a gate, or lower a statistical bar to make
something pass.** If a gate can only be passed by lowering it, the answer is
that the thing does not pass. Say so. A unit that ends by reporting the
approach does not work is a successful unit.

## When to stop and report

Stopping is a correct outcome here and is preferred over a guess. Stop when:

- Two sources of truth disagree. Surface the conflict; do not silently take the
  more permissive reading.
- Your unit appears to need a file outside its declared paths.
- The only way to pass a gate is to loosen it.
- A timestamp ordering is ambiguous for a real feed and you would have to
  invent a rule to proceed.
- `scripts/verify_harness.sh` was already failing when you arrived, before you
  changed anything. That is an environment problem, not a verdict on your unit.
  Report it with the exact failing commands.

When you stop, say precisely what blocked you, and what you did and did not
change.

## Known hazards, learned the hard way

**A stale interpreter can disarm the guard.** On macOS, `python3` resolves to
3.9, the guard dies with a `SyntaxError`, and both runtimes read a non-2 exit
as non-blocking, so the safety hook fails open silently. This is why every
interpreter call goes through `scripts/hook_python.sh`, which exits 2 when no
usable interpreter exists. Use it rather than a bare `python3` in any tooling
you add.

**Uncommitted work is lost work.** Commit on your branch as you go. The branch
is how your output reaches anyone.

**A fresh worktree has no virtualenv.** Run `uv sync --frozen` in it before the
first `uv run`, or the gate fails for a reason that has nothing to do with your
code.

**`.claude/settings.local.json` is untracked** and does not carry into a
worktree. Copy it in, or the MCP server is silently absent.

## Reporting back

When a unit is done, the summary should say: what you implemented, the exact
commands you ran and their output, which acceptance criteria you believe are
met, and what remains unverified.

That last part is not a formality. Never call a path verified when it was only
inspected. If you did not run it, say you did not run it.
