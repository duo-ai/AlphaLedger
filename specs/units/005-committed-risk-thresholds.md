---
id: UNIT-005
title: Commit the risk thresholds design section 10 requires
lane: shared
state: available
owner: -
branch: -
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-004, UNIT-013, UNIT-017]
paths: config/risk.toml, src/alphaledger/config/**, tests/test_config.py
---

## Problem

Three thresholds design section 10 requires are committed nowhere.
`config/risk.toml` holds eight keys and none of them is `max_snapshot_age`,
`daily_loss_stop_fraction`, or `peak_to_valley_fraction`. Verified against the
file on 2026-08-30, not inferred from the status note that first recorded it.

The consequence is already visible in merged code. `UNIT-013`'s `approve` takes
`max_snapshot_age` as a required explicit parameter, and `UNIT-017`'s
`evaluate_kill_switch` takes `daily_loss_stop_fraction` and
`peak_to_valley_fraction` the same way, because there was nothing to read them
from. Each unit recorded that as a gap rather than a design.

D-017 is the reason this matters more than tidiness. A value a reader of the
evidence ledger would need in order to understand why a decision was made is
committed, so that it can be hashed into the run manifest and proven after the
fact. A risk limit passed as a bare argument is not in `risk_config_hash`, so a
session that halted on a kill switch cannot later prove which threshold it
halted on. That turns the ledger from evidence into an assertion, for precisely
the three values most in need of being frozen before an autonomous session.

## Source of truth

- `options-alpha-agent-design.md` section 10, which supplies two of the three
  numbers directly: a daily realized plus unrealized loss stop at 1.5% of
  session-start equity, and a peak-to-valley equity kill switch at 3.0%.
- `project-state/DECISIONS.md`, D-017, for which values are committed and why.
- `specs/units/013-risk-approval-token.md` and
  `specs/units/017-kill-switch.md`, whose signatures this unit exists to let a
  caller satisfy from frozen configuration.
- `specs/units/004-frozen-config.md`, whose loader and drift test this extends.

## Scope

In:

- Three keys in `config/risk.toml`, with the two section 10 values and one
  staleness bound.
- Loading them through `alphaledger.config` into the existing frozen record, so
  they enter the content hash `UNIT-004` already computes.
- Extending `UNIT-004`'s drift test so a value cannot diverge from whatever
  dataclass default still mirrors it.

Out:

- Changing `approve` or `evaluate_kill_switch`. Their signatures stay as
  merged. This unit gives a caller something to pass; it does not change what
  they accept, and narrowing a merged signature would reopen two reviewed
  units for no gain.
- Selecting any of the three on data. Every value here is declared, exactly as
  D-017 records for every value already in `config/`.
- The remaining section 10 limits that are already present or already absent
  for separate reasons. This unit closes the three named above and no others.

## Contract

`config/risk.toml` gains, as TOML values that survive the money rules already
in force, so a fraction is a float and never a bare decimal string that
`money()` would reject on read:

```toml
max_snapshot_age_seconds = 30
daily_loss_stop_fraction = 0.015
peak_to_valley_fraction = 0.03
```

`alphaledger.config`'s frozen risk record gains the three fields, and
`max_snapshot_age_seconds` is exposed to callers as a `timedelta` so a caller
cannot pass a number of seconds where `approve` expects a duration.

## When you do not know

Two of the three numbers come from design section 10's own table and are not a
judgement call: 1.5% and 3.0%.

`max_snapshot_age` has no number anywhere in the design. Section 10 requires
that there be no trade during a stale-data incident and never says how old is
stale. Thirty seconds is proposed as a declared default on the same footing as
every other value in `config/`, none of which has been selected on data either,
and it is deliberately committed rather than left out so that it is hashed and
auditable. It is not marked `[NEEDS CLARIFICATION]`, because doing so would
make the unit unclaimable and block the two values that the design does
specify, which would be the marker preventing work rather than preventing a
guess. Whoever freezes the risk configuration before an autonomous session
should revisit this one specifically; the other two are settled.

## Assumptions

The fractions are of the equity base each merged unit already uses: session
start equity for the daily stop, and peak equity for the peak-to-valley
comparison. This unit does not restate those definitions, which live with
`UNIT-017`, and must not redefine them.

## Acceptance criteria

- AC-1: the three keys are present in `config/risk.toml` and reachable through
  the frozen record. Falsified by loading the configuration and observing any
  of the three absent or defaulted in code.
- AC-2: changing any of the three changes the risk configuration hash.
  Falsified by editing one and observing the hash hold, which would mean a
  session could not prove which threshold it ran under.
- AC-3: `max_snapshot_age` reaches a caller as a `timedelta`, not as a number.
  Falsified by observing an `int` or `float` where `approve` expects a
  duration, which is the shape that silently passes thirty milliseconds where
  thirty seconds was meant.
- AC-4: `UNIT-004`'s drift test covers the three new values, so a code default
  and a committed value cannot diverge silently. Falsified by changing one in
  isolation and observing the suite stay green.
- AC-5: no merged signature changes. Falsified by any diff to
  `src/alphaledger/risk/` or `src/alphaledger/execution/killswitch.py`.

## Test list

- success: the three values load and carry the documented numbers.
- success: `max_snapshot_age` is a `timedelta` of thirty seconds.
- failure: each of the three, changed alone, changes the configuration hash.
- failure: a negative or zero value for any of the three is refused, since each
  is a bound that would disable the gate it belongs to.
- restart: the same committed file produces the same hash in a separate
  process, under two `PYTHONHASHSEED` values.
- no-trade: the values are readable without a broker, a clock, or a network,
  because a fail-closed halt has to be able to state its own threshold.

## Verification

```bash
uv run pytest tests/test_config.py
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
